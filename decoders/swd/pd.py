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
import re
from enum import Enum, unique, auto
from typing import Literal

'''
OUTPUT_PYTHON format:

Packet:
[<ptype>, <pdata>]

<ptype>:
 - 'AP_READ' (AP read)
 - 'DP_READ' (DP read)
 - 'AP_WRITE' (AP write)
 - 'DP_WRITE' (DP write)
 - 'LINE_RESET' (line reset sequence)

<pdata>:
  - tuple of address, ack state, data for the given sequence
'''

Bit = Literal[0, 1]

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
	selectionAlert = auto()
	activation = auto()

# Regexes for matching SWD data out of bitstring ('1' / '0' characters) format
RE_SWDSWITCH = re.compile(bin(0xE79E)[:1:-1] + '$')
RE_SWDREQ = re.compile(r'1(?P<apdp>.)(?P<rw>.)(?P<addr>..)(?P<parity>.)01$')
RE_IDLE = re.compile('0' * 50 + '$')

# Sample edges
RISING = 1
FALLING = 0

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
	) = range(9)
A = Annotations

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
		('idle', 'IDLE'),
		('reset', 'RESET'),
		('enable', 'ENABLE'),
		('read', 'READ'),
		('write', 'WRITE'),
		('ack', 'ACK'),
		('data', 'DATA'),
		('parity', 'PARITY'),
		('error', 'ERROR'),
	)

	def __init__(self):
		pass

	def reset(self):
		# initial SWD data/clock state (presume the bus is idle)
		self.state = DecoderState.unknown
		self.startSample = 0
		self.request = 0
		self.ack = 0
		self.bits = 0

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

	def handle_request(self):
		# Was this the start of one of the special sequences?
		if self.request == 0xc9:
			self.state = DecoderState.selectionAlert
			self.request <<= 120
			self.bits += 1
			return

		# If the stop bit is high, then this was actually a part of a line reset (probably?)
		if (self.request & (1 << 6)) != 0:
			self.state = DecoderState.reset
			return

		# Figure out if this is an AP or a DP access
		target = 'DP' if (self.request & (1 << 1)) == 0 else 'AP'

		# Determine if this is a read or a write
		if (self.request & (1 << 2)) != 0:
			self.annotateBits(self.startSample, self.samplenum, [A.READ, [f'{target} READ', f'{target} RD', f'{target[0]}R']])
		else:
			self.annotateBits(self.startSample, self.samplenum, [A.WRITE, [f'{target} WRITE', f'{target} WR', f'{target[0]}W']])
		self.state = DecoderState.ackTurnaround

	def handle_swclk_edge(self, swclk: Bit, swdio: Bit):
		match self.state:
			case DecoderState.unknown:
				# If we're waiting on a line reset, then look only for a rising edge with swdio high
				if swclk == 1 and swdio == 1:
					self.startSample = self.samplenum
					self.bits = 1
					self.state = Decoder.reset

			case DecoderState.idle:
				# If this is the rising edge of the clock, check to see if we are leaving idle
				if swclk == 1 and swdio == 1:
					self.state = DecoderState.request
					self.request = 0x80
					self.bits = 1
					self.annotateBits(self.startSample, self.samplenum, [A.IDLE, ['IDLE', 'I']])
					self.startSample = self.samplenum

			case DecoderState.reset:
				# line reset only cares about the line being kept high on rising edges
				if swclk == 1:
					if swdio == 1:
						self.bits += 1
					else:
						# Check if we've got enough bits to consider this line reset
						if self.bits >= 50:
							self.state = DecoderState.idle
							self.annotateBits(self.startSample, self.samplenum, [A.RESET, ['LINE RESET', 'LN RST', 'LR']])
							self.startSample = self.samplenum
						# If we do not, then we're now back in an unknown state
						else:
							self.state = DecoderState.unknown

			case DecoderState.request:
				# Consume the next bit on the rising edge of the clock
				if swclk == 1:
					self.request >>= 1
					self.request |= (swdio << 7)
					self.bits += 1
				elif self.bits == 8:
					# If we've now consumed a full request's worth of bits, figure out what it is we got
					self.handle_request()

			case DecoderState.ackTurnaround:
				# If we saw the falling edge of the turnaround clock edge, start pulling in the ACK bits
				if swclk == 0:
					self.bits = 1
					self.ack = (swdio << 2)
					self.state = DecoderState.ack
					self.startSample = self.samplenum

			case DecoderState.ack:
				# Sample the ACK bits on the falling edges
				if swclk == 0:
					self.ack >>= 1
					self.ack |= (swdio << 2)
					self.bits += 1
				elif self.bits == 3:
					# If this is a write, we have one more turnaround to do - otherwise it's into
					# the data phase for a read.
					if (self.request & (1 << 2)) == 1:
						self.state = DecoderState.dataRead
					else:
						self.state = DecoderState.dataTurnaround
						self.bits = 0

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

			case DecoderState.selectionAlert:
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
							self.annotateBits(self.startSample, self.samplenum, [A.ERROR, [f'INVALID SEQUENCE {self.request:x}', 'INV SEQ', 'IS']])
					else:
						self.request >>= 1
						self.request |= (swdio << 127)
						self.bits += 1

			case DecoderState.activation:
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

	def decode(self):
		while True:
			# Wait for any clock edge.
			self.handle_swclk_edge(*self.wait({0: 'e'}))
