#
# This file is part of the libsigrokdecode project.
#
# Copyright (C) 2014 Angus Gratton <gus@projectgus.com>
# Copyright (C) 2024 Rachel Mant <git@dragonmux.network>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.
#

import sigrokdecode as srd
from enum import Enum, unique, auto
from typing import Literal

'''
OUTPUT_PYTHON format:

Packet:
(<op>, <dp>, <addr>, <reg>, <ack>, <data>)

<op>:
	- 'DP_READ'
	- 'DP_WRITE'
	- 'AP_READ'
	- 'AP_WRITE'
	- 'LINE_RESET' (line reset sequence)

<dp>:
integer index of the DP to which the operation was requested

<addr>:
8-bit address of the operation

<reg>:
The decoded register name for the operation

<ack>
	- 'OK'
	- 'WAIT'
	- 'FAULT'

<data>
32-bit data value associated with the operation
'''

__all__ = ['Decoder']

Bit = Literal[0, 1]

class Annotations:
	'''Annotation and binary output classes.'''
	(
		IDLE,
		RESET,
		ENABLE,
		READ,
		WRITE,
		ACK,
		DATA,
		PARITY,
		ERROR,
		ADIV5_ACK_OK,
		ADIV5_ACK_WAIT,
		ADIV5_ACK_FAULT,
		ADIV5_REGISTER,
		ADIV5_DATA,
	) = range(14)
A = Annotations

ADIv5Op = Literal['DP_READ', 'DP_WRITE', 'AP_READ', 'AP_WRITE', 'LINE_RESET']
ADIv5Ack = Literal['OK', 'WAIT', 'FAULT']

@unique
class DecoderState(Enum):
	unknown = auto()
	idle = auto()
	reset = auto()
	request = auto()
	ackTurnaround = auto()
	ack = auto()
	dataTurnaround = auto()
	dataRead = auto()
	dataWrite = auto()
	parity = auto()
	sync = auto()
	idleTurnaround = auto()
	waitIdle = auto()
	deactivation = auto()
	selectionAlert = auto()
	activation = auto()
	dormantState = auto()
	jtagToSWD = auto()

@unique
class SelectionState(Enum):
	unknown = auto()
	reset = auto()
	selecting = auto()
	made = auto()

class Decoder(srd.Decoder):
	api_version = 3
	id = 'swd'
	name = 'SWD'
	longname = 'Serial Wire Debug'
	desc = 'Two-wire protocol for debug access to ARM CPUs.'
	license = 'gplv2+'
	inputs = ['logic']
	outputs = ['adi']
	tags = ['Debug/trace']
	channels = (
		{'id': 'swclk', 'name': 'SWCLK', 'desc': 'Master clock'},
		{'id': 'swdio', 'name': 'SWDIO', 'desc': 'Data input/output'},
	)
	options = (
		{
			'id': 'strict_start',
			'desc': 'Wait for a line reset before starting to decode',
			'default': 'no',
			'values': ('yes', 'no')
		},
	)
	annotations = (
		# SWD state annotations
		('idle', 'Idle'),
		('reset', 'Reset'),
		('enable', 'Enable'),
		('read', 'Read'),
		('write', 'Write'),
		('ack', 'Acknowledgement'),
		('data', 'Data'),
		('parity', 'Parity'),
		('error', 'Error'),
		# ADIv5 acknowledgement annotations
		('adiv5-ack-ok', 'ACK (OK)'),
		('adiv5-ack-wait', 'ACK (WAIT)'),
		('adiv5-ack-fault', 'ACK (FAULT)'),
		# ADIv5 transaction annotations
		('adiv5-register', 'Register'),
		('adiv5-data', 'Data'),
	)
	annotation_rows = (
		('states', 'States', (A.IDLE, A.RESET, A.ENABLE, A.READ, A.WRITE, A.ACK, A.DATA, A.PARITY, A.ERROR)),
		('transactions', 'Transaction',
			(A.ADIV5_ACK_OK, A.ADIV5_ACK_WAIT, A.ADIV5_ACK_FAULT, A.ADIV5_REGISTER, A.ADIV5_DATA)),
	)

	def __init__(self):
		pass

	def reset(self):
		# initial SWD data/clock state (presume the bus is idle)
		self.state = DecoderState.unknown
		self.startSample = 0
		self.request = 0
		self.ack = 0
		self.data = 0
		self.computedParity = 0
		self.actualParity = 0
		self.bits = 0
		self.selectionState = SelectionState.unknown

	def start(self):
		self.reset()
		self.outputAnnotation = self.register(srd.OUTPUT_ANN)
		self.outputPython = self.register(srd.OUTPUT_PYTHON)
		if self.options['strict_start'] == 'no':
			self.state = DecoderState.idle # No need to wait for a LINE RESET.

	def annotateBits(self, begin: int, end: int, data: list[int | list[str]]):
		self.put(begin, end, self.outputAnnotation, data)

	def annotateBit(self, bit: int, data: list[int | list[str]]):
		self.annotateBits(bit, bit, data)

	def processRequest(self):
		# Was this the start of one of the special sequences?
		if self.request == 0xc9:
			self.state = DecoderState.selectionAlert
			self.request <<= 120
			self.bits += 1
			return
		elif self.request == 0xdd:
			self.state = DecoderState.deactivation
			self.request <<= 23
			self.bits += 1
			return
		elif self.request == 0xcf and self.selectionState == SelectionState.reset:
			self.state = DecoderState.jtagToSWD
			self.request <<= 8
			self.bits += 1
			return

		# If the stop bit is high, then this was actually a part of a line reset (probably?)
		if (self.request & (1 << 6)) != 0:
			self.state = DecoderState.reset
			return

		# Figure out if this is an AP or a DP access
		target = 'DP' if (self.request & (1 << 1)) == 0 else 'AP'

		if self.selectionState == SelectionState.reset:
			if self.request == 0x99:
				self.selectionState = SelectionState.selecting
			else:
				self.selectionState = SelectionState.unknown

		# Determine if this is a read or a write
		if (self.request & (1 << 2)) != 0:
			self.annotateBits(self.startSample, self.samplenum, [A.READ, [f'{target} READ', f'{target} RD', f'{target[0]}R']])
		else:
			self.annotateBits(self.startSample, self.samplenum, [A.WRITE, [f'{target} WRITE', f'{target} WR', f'{target[0]}W']])
		self.state = DecoderState.ackTurnaround

	def processAck(self):
		match self.ack:
			# OK Ack
			case 1:
				# If this is a write, we have one more turnaround to do - otherwise it's into
				# the data phase for a read.
				if (self.request & (1 << 2)) != 0:
					self.state = DecoderState.dataRead
					self.data = 0
					self.computedParity = 0
				else:
					self.state = DecoderState.dataTurnaround
				self.bits = 0
			# WAIT Ack
			case 2:
				# Nothing more to do, just wait for the final turnaround for bus idle, and idle
				self.state = DecoderState.sync
			# FAULT Ack
			case 4:
				# Similarly to WAIT, we're done.. wait for idle
				self.state = DecoderState.sync
			# NO-RESPONSE Ack
			case 7:
				# If the request is to TARGETSEL, we actually now have a write that occurs, selecting
				# a target on the bus. This must be after a fresh line reset.
				if self.selectionState == SelectionState.selecting:
					self.state = DecoderState.dataTurnaround
				else:
					self.state = DecoderState.waitIdle
				self.bits = 0
			# Anything else is a protocol error
			case _:
				self.state = DecoderState.unknown

	def handleUnknown(self, swclk: Bit, swdio: Bit):
		# If we're waiting on a line reset, then look only for a rising edge with swdio high
		if swclk == 1 and swdio == 1:
			self.startSample = self.samplenum
			self.bits = 1
			self.state = Decoder.reset

	def handleIdle(self, swclk: Bit, swdio: Bit):
		# If this is the rising edge of the clock, check to see if we are leaving idle
		if swclk == 1 and swdio == 1:
			self.state = DecoderState.request
			self.request = 0x80
			self.bits = 1
			self.annotateBits(self.startSample, self.samplenum, [A.IDLE, ['IDLE', 'I']])
			self.startSample = self.samplenum

	def handleReset(self, swclk: Bit, swdio: Bit):
		# line reset only cares about the line being kept high on rising edges
		if swclk == 1:
			if swdio == 1:
				self.bits += 1
			else:
				# Check if we've got enough bits to consider this line reset
				if self.bits >= 50:
					self.state = DecoderState.idle
					self.selectionState = SelectionState.reset
					self.annotateBits(self.startSample, self.samplenum, [A.RESET, ['LINE RESET', 'LN RST', 'LR']])
					self.startSample = self.samplenum
				# If we do not, then we're now back in an unknown state
				else:
					self.state = DecoderState.unknown

	def handleRequest(self, swclk: Bit, swdio: Bit):
		# Consume the next bit on the rising edge of the clock
		if swclk == 1:
			self.request >>= 1
			self.request |= (swdio << 7)
			self.bits += 1
		elif self.bits == 8:
			# If we've now consumed a full request's worth of bits, figure out what it is we got
			self.processRequest()

	def handleAckTurnaround(self, swclk: Bit, swdio: Bit):
		# If we saw the falling edge of the turnaround clock cycle, start pulling in the ACK bits
		if swclk == 0:
			self.bits = 1
			self.ack = (swdio << 2)
			self.state = DecoderState.ack
			self.startSample = self.samplenum

	def handleAck(self, swclk: Bit, swdio: Bit):
		# Sample the ACK bits on the falling edges
		if swclk == 0:
			self.ack >>= 1
			self.ack |= (swdio << 2)
			self.bits += 1
		elif self.bits == 3:
			# Figure out what kind of ACK this was and annotate it
			self.annotateBits(
				self.startSample, self.samplenum,
				[
					A.ACK,
					[
						{
							1: 'OK',
							2: 'WAIT',
							4: 'FAULT',
							7: 'NO-RESPONSE'
						}.get(self.ack, 'UNKNOWN')
					]
				]
			)
			self.startSample = self.samplenum
			# Now turn the ack into an appropriate state change
			self.processAck()

	def handleDataTurnaround(self, swclk: Bit):
		# If we saw the falling edge of the turnaround cycle, start pulling in data bits
		if swclk == 0:
			if self.bits == 1:
				self.bits = 0
				self.data = 0
				self.computedParity = 0
				self.state = DecoderState.dataWrite
				self.startSample = self.samplenum
			else:
				self.bits += 1

	def handleDataRead(self, swclk: Bit, swdio: Bit):
		# Sample the data on the falling edges
		if swclk == 0:
			# If this is a data bit, shuffle it into the data collection
			if self.bits < 32:
				self.data >>= 1
				self.data |= (swdio << 31)
				self.computedParity ^= swdio
			# Otherwise grab the pairty bit
			else:
				self.actualParity = swdio
				self.state = DecoderState.parity
			self.bits += 1
		else:
			# If we have all the data bits, annotate
			if self.bits == 32:
				self.annotateBits(self.startSample, self.samplenum, [A.DATA, [f'{self.data:08x}']])
				self.startSample = self.samplenum

	def handleDataWrite(self, swclk: Bit, swdio: Bit):
		# Sample the data on the rising edges
		if swclk == 1:
			# If this is a data bit, shuffle it into the data collection
			if self.bits < 32:
				self.data >>= 1
				self.data |= (swdio << 31)
				self.computedParity ^= swdio
			# Otherwise grab the pairty bit
			else:
				self.actualParity = swdio
				self.state = DecoderState.parity
			self.bits += 1
		else:
			# If we have all the data bits, annotate
			if self.bits == 32:
				self.annotateBits(self.startSample, self.samplenum, [A.DATA, [f'{self.data:08x}']])
				self.startSample = self.samplenum
				if self.selectionState == SelectionState.selecting:
					self.selectionState = SelectionState.made

	def handleParity(self, swclk: Bit):
		# Make sure this is a falling clock edge
		if swclk == 0:
			# We now have the parity bit, check what state the parity result is, annotate,
			# and wait for the last turnaround
			parity = 'OK' if self.computedParity == self.actualParity else 'ERROR'
			self.annotateBits(
				self.startSample, self.samplenum,
				[A.PARITY, [f'PARITY {parity}', parity, parity[0]]]
			)
			self.state = DecoderState.idleTurnaround

	def handleSync(self, swclk: Bit):
		# If we just saw a falling edge, we're finally properly done with the ACK bits and can now do the
		# bus idle turnaround cycle handling
		if swclk == 0:
			self.state = DecoderState.idleTurnaround

	def handleIdleTurnaround(self, swclk: Bit):
		# Once we see the falling edge, we can relax and go to idle
		if swclk == 0:
			self.state = DecoderState.idle
			self.startSample = self.samplenum

	def handleWaitIdle(self, swclk: Bit, swdio: Bit):
		# Wait until we see SWDIO go back low, indicating the debugger idled the bus at last
		if swclk == 1:
			if swdio == 0:
				self.state = DecoderState.idle
				self.startSample = self.samplenum
			else:
				self.bits += 1
		# If we got more than 34 bits high, the debugger's blown past the 33 bits for the request and the
		# idle turnaround, so we're now in reset
		elif self.bits > 34:
			self.state = DecoderState.reset

	def handleDeactivation(self, swclk: Bit, swdio: Bit):
		# Consume the next bit on the rising edge of the clock
		if swclk == 1:
			# Check we've got a complete sequence
			if self.bits == 31:
				# Is it a valid JTAG-to-dormant sequence
				if self.request == 0x33bbbbba:
					self.state = DecoderState.dormantState
					self.request = swdio
					self.bits = 0
					self.annotateBits(self.startSample, self.samplenum, [A.ENABLE, ['DORMANT SEQUENCE', 'DORMANT', 'DS']])
					self.startSample = self.samplenum
				else:
					# We got an invalid sequence, mark the error and go to the unknown state
					self.state = DecoderState.unknown
					self.annotateBits(self.startSample, self.samplenum,
						[A.ERROR, [f'INVALID SEQUENCE {self.request:x}', 'INV SEQ', 'IS']])
			else:
				self.request >>= 1
				self.request |= (swdio << 30)
				self.bits += 1

	def handleSelectionAlert(self, swclk: Bit, swdio: Bit):
		# Consume the next bit on the rising edge of the clock
		if swclk == 1:
			# Check we've got a complete sequence
			if self.bits == 128:
				# Is it a valid Alert Sequence?
				if self.request == 0x19bc0ea2e3ddafe986852d956209f392:
					# Mark it, wait for the activation sequence
					self.state = DecoderState.activation
					self.request = swdio
					self.bits = 1
					self.annotateBits(self.startSample, self.samplenum, [A.ENABLE, ['ALERT SEQUENCE', 'ALERT', 'AS']])
					self.startSample = self.samplenum
				else:
					# We got an invalid sequence, mark the error and go to the unknown state
					self.state = DecoderState.unknown
					self.annotateBits(self.startSample, self.samplenum,
						[A.ERROR, [f'INVALID SEQUENCE {self.request:x}', 'INV SEQ', 'IS']])
			else:
				self.request >>= 1
				self.request |= (swdio << 127)
				self.bits += 1

	def handleActivation(self, swclk: Bit, swdio: Bit):
		if swclk == 1:
			# Consume the first 4 bits and ensure they're all 0
			if self.bits < 4:
				# If we got a bad sequence, abort and go to unknown state
				if swdio == 1:
					self.state = DecoderState.unknown
					self.annotateBits(self.startSample, self.samplenum, [A.ERROR, ['INVALID IDLE', 'INV IDLE', 'II']])
				else:
					self.bits += 1
			else:
				# Check if the sequence finally matched one of the activation sequences
				if self.request == 0x58:
					# SWD selected -> go to happy place idle
					self.state = DecoderState.reset
					self.bits = 0
					self.annotateBits(self.startSample, self.samplenum, [A.ENABLE, ['ACTIVATE SWD', 'ACTIVATE', 'AS']])
					self.startSample = self.samplenum
				elif self.request == 0x50:
					# JTAG selected -> go to unknown till we see a line reset
					self.state = DecoderState.unknown
					self.annotateBits(self.startSample, self.samplenum, [A.ENABLE, ['ACTIVATE JTAG', 'ACTIVATE', 'AJ']])
				else:
					# Pull the next bit (NB, this means the result value is in big bit endian!!)
					self.request <<= 1
					self.request |= swdio
					self.request &= 0xff

	def handleDormantState(self, swclk: Bit, swdio: Bit):
		# Consume the next bit on the rising edge of the clock
		if swclk == 1:
			# Consume bits until we've seen 8 highs in a row
			if self.bits == 0 and self.request != 0xff:
				self.request <<= 1
				self.request |= swdio
				self.request &= 0xff
			# If we matched reset, start pulling in bits for the selection alert sequence
			elif self.bits == 0 and self.request == 0xff:
				self.request = (swdio << 7)
				self.bits += 1
				self.annotateBits(self.startSample, self.samplenum, [A.IDLE, ['DORMANT', 'D']])
				self.startSample = self.samplenum
			else:
				self.request >>= 1
				self.request |= (swdio << 7)
				self.bits += 1
		# If we've got a full suite of bits, figure out if it was the first part of selection sequence, or not
		elif self.bits == 9:
			# If it is a selection alert start, great!
			if self.request == 0xc9:
				self.state = DecoderState.selectionAlert
				self.request <<= 120
			# Otherwise, reset self.bits and go back around the loop
			else:
				self.bits = 0

	def handleJTAGtoSWD(self, swclk: Bit, swdio: Bit):
		# Consume the next bit on the rising edge of the clock
		if swclk == 1:
			self.request >>= 1
			self.request |= (swdio << 15)
			self.bits += 1
		# If we've got all the bits for the sequence
		elif self.bits == 16:
			# Validate we got the right one
			if self.request == 0xe79e:
				self.state = DecoderState.reset
				self.bits = 0
				self.annotateBits(self.startSample, self.samplenum, [A.ENABLE, ['JTAG to SWD', 'J->S', 'JS']])
				self.startSample = self.samplenum

	def handleClkEdge(self, swclk: Bit, swdio: Bit):
		match self.state:
			case DecoderState.unknown:
				self.handleUnknown(swclk, swdio)
			case DecoderState.idle:
				self.handleIdle(swclk, swdio)
			case DecoderState.reset:
				self.handleReset(swclk, swdio)
			case DecoderState.request:
				self.handleRequest(swclk, swdio)
			case DecoderState.ackTurnaround:
				self.handleAckTurnaround(swclk, swdio)
			case DecoderState.ack:
				self.handleAck(swclk, swdio)
			case DecoderState.dataTurnaround:
				self.handleDataTurnaround(swclk)
			case DecoderState.dataRead:
				self.handleDataRead(swclk, swdio)
			case DecoderState.dataWrite:
				self.handleDataWrite(swclk, swdio)
			case DecoderState.parity:
				self.handleParity(swclk)
			case DecoderState.sync:
				self.handleSync(swclk)
			case DecoderState.idleTurnaround:
				self.handleIdleTurnaround(swclk)
			case DecoderState.waitIdle:
				self.handleWaitIdle(swclk, swdio)
			case DecoderState.deactivation:
				self.handleDeactivation(swclk, swdio)
			case DecoderState.selectionAlert:
				self.handleSelectionAlert(swclk, swdio)
			case DecoderState.activation:
				self.handleActivation(swclk, swdio)
			case DecoderState.dormantState:
				self.handleDormantState(swclk, swdio)
			case DecoderState.jtagToSWD:
				self.handleJTAGtoSWD(swclk, swdio)

	def decode(self):
		while True:
			# Wait for any clock edge.
			self.handleClkEdge(*self.wait({0: 'e'}))
