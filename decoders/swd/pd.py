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
			'default': 'no', 'values': ('yes', 'no')
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

		# If the stop bit is high, then this was actually a part of a line reset (probably?)
		if (self.request & (1 << 7)) != 0:
			self.state = DecoderState.reset
			return

		# Determine if this is a read or a write
		if self.request & (1 << 3):
			self.annotateBits(self.startSample, self.samplenum, [A.READ, [f'{self.request:x}']])
		else:
			self.annotateBits(self.startSample, self.samplenum, [A.WRITE, [f'{self.request:x}']])
		self.state = DecoderState.ackTurnaround

	def handle_swclk_edge(self, swclk, swdio):
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
					# If we've now consumed a full request's worth of bits, figure out what it is we got
					if self.bits == 8:
						self.handle_request()
			case DecoderState.ackTurnaround:
				# If we saw the rising edge of the turnaround clock edge, start pulling in the ACK bits
				if swclk == 1:
					self.bits = 0
					self.ack = 0
					self.state = DecoderState.ack
					self.startSample = self.samplenum

	def decode(self):
		while True:
			# Wait for any clock edge.
			self.handle_swclk_edge(*self.wait({0: 'e'}))
