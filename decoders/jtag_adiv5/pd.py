##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2024 Rachel Mant <git@dragonmux.network>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
##

import sigrokdecode as srd
from typing import Union
from enum import Enum, unique, auto

__all__ = ['Decoder']

class Annotations:
	'''Annotation and binary output classes.'''
	(
		JTAG_ITEM, JTAG_FIELD, JTAG_COMMAND, JTAG_NOTE,
		ADIV5_ACK_OK, ADIV5_ACK_WAIT, ADIV5_ACK_FAULT,
		ADIV5_READ, ADIV5_WRITE, ADIV5_REGISTER,
		ADIV5_REQUEST, ADIV5_RESULT,
	) = range(12)
A = Annotations

@unique
class ADIv5State(Enum):
	idle = auto()
	dpAccess = auto()
	apAccess = auto()
	inError = auto()

@unique
class DecoderState(Enum):
	inactive = auto()
	idle = auto()
	awaitingIDCodes = auto()
	countingDevices = auto()
	awaitingIR = auto()
	awaitingDR = auto()
	inError = auto()

class JTAGDevice:
	idcode: int
	currentIR: int

	drPrescan: int
	drPostscan: int

	irLength: int
	irPrescan: int
	irPostscan: int

	def __init__(self, drPrescan: int, idcode: int):
		self.idcode = idcode
		self.drPrescan = drPrescan

	@property
	def isADIv5(self):
		'''Check if this ID code is one for an ARM ADIv5 TAP'''
		return (self.idcode & 0x0fff0fff) == 0x0ba00477

	def __str__(self):
		return f'<JTAGDevice {self.drPrescan}: {self.idcode:08x}>'

class ADIv5Decoder:
	def __init__(self, decoder: 'Decoder'):
		self.decoder = decoder
		self.reset()

	def reset(self):
		self.state = ADIv5State.idle

class Decoder(srd.Decoder):
	api_version = 3
	id = 'jtag_arm'
	name = 'JTAG / ADIv5'
	longname = 'Joint Test Action Group / ARM ADIv5'
	desc = 'ARM ADIv5 JTAG debug protocol.'
	license = 'gplv2+'
	inputs = ['jtag']
	outputs = ['adiv5']
	tags = ['Debug/trace']
	annotations = (
		# JTAG encapsulation annotations
		('item', 'Item'),
		('field', 'Field'),
		('command', 'Command'),
		('note', 'Note'),
		# ADIv5 acknowledgement annotations
		('adiv5-ack-ok', 'ACK (OK)'),
		('adiv5-ack-wait', 'ACK (WAIT)'),
		('adiv5-ack-fault', 'ACK (FAULT)'),
		# ADIv5 request annotations
		('adiv5-read', 'Read'),
		('adiv5-write', 'Write'),
		('adiv5-register', 'Register'),
		# ADIv5 data annotations
		('adiv5-request', 'Request'),
		('adiv5-result', 'Result'),
	)
	annotation_rows = (
		('items', 'Items', (A.JTAG_ITEM,)),
		('fields', 'Fields', (A.JTAG_FIELD,)),
		('commands', 'Commands', (A.JTAG_COMMAND,)),
		('notes', 'Notes', (A.JTAG_NOTE,)),
		('request', 'Request', (A.ADIV5_READ, A.ADIV5_WRITE, A.ADIV5_REGISTER, A.ADIV5_REQUEST)),
		('result', 'Result', (A.ADIV5_ACK_OK, A.ADIV5_ACK_WAIT, A.ADIV5_ACK_FAULT, A.ADIV5_RESULT)),
	)

	def __init__(self):
		self.beginSample = 0
		self.endSample = 0
		self.devices: list[JTAGDevice] = []
		self.decoders: list[ADIv5Decoder] = []

	def reset(self):
		self.state = DecoderState.inactive
		self.decoders.clear()

	def start(self):
		self.reset()
		self.outputAnnotation = self.register(srd.OUTPUT_ANN)

	def putx(self, data: list[int, list[str]]):
		self.put(self.beginSample, self.endSample, self.outputAnnotation, data)

	def putf(self, start: list[int], end: list[int], data: list[int, list[str]]):
		self.put(start[0], end[0], self.outputAnnotation, data)

	def putb(self, bit: list[int], data: list[int, list[str]]):
		self.putf(bit, bit, data)

	def decode(self, beginSample: int, endSample: int, data: tuple[str, Union[str, tuple[str, list[list[int]]]]]):
		'''Take a transaction from the JTAG decoder and decode it into an ADIv5 transaction

		The data input has either the form ('NEW STATE', stateName), or (stateName, (bitstring, [samplePositions])).
		As we don't actually care about state changes beyond detecting when we go into a new shift state.
		As such, we mostly discard this former sort, and instead focus on decoding the bitstrings of data
		from in a state.

		NB: both the IR and DR shift states produce both TDI and TDO data tuples, it's on us to determine
		which of the two holds any actually useful data.
		'''
		self.beginSample = beginSample
		self.endSample = endSample
		action, value = data

		# If this is a state change message, figure out if we care
		if action == 'NEW STATE':
			assert isinstance(value, str)
			self.handleStateChange(value)

	def handleStateChange(self, state: str):
		'''Takes a new state transition from the JTAG decoder and picks out DR and IR shift states to arm
		the ADIv5 decoders for new data/instructions
		'''
		# If we got a TLR, honour the reset
		if self.state != DecoderState.awaitingIDCodes and state == 'TEST-LOGIC-RESET':
			self.state = DecoderState.awaitingIDCodes
			self.decoders.clear()
		elif self.state == DecoderState.idle:
			# If we're all configured and we see Shift-IR, await the new IR value
			if state == 'SHIFT-IR':
				self.state = DecoderState.awaitingIR
			# If we're all configured and we see Shift-DR, await the new DR exchange
			elif state == 'SHIFT-DR':
				self.state = DecoderState.awaitingDR
