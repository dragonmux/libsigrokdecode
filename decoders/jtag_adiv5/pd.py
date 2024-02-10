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
from .devices import jtagDevices

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

def fromBitstring(bits: str, begin: int, end: int) -> int:
	'''Grab a chunk from a big bit endian bitstring, and decode it to an integer

	`begin` is the first logical bit desired, `end` is the last forming
	an interval of the form [begin:end)
	'''
	length = len(bits)
	substr = bits[length - end:length - begin]
	return int(substr, base = 2)

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
		self.quirks = None

	@property
	def isADIv5(self):
		'''Check if this ID code is one for an ARM ADIv5 TAP'''
		return (self.idcode & 0x0fff0fff) == 0x0ba00477

	@property
	def hasQuirks(self):
		return self.quirks is not None

	def decodeIDCode(self):
		# Try and find the ID code in the known devices list
		for device in jtagDevices:
			if (self. idcode & device['mask']) == device['idcode']:
				# If we get a match, now unpack any quirks information that might be present
				if 'irQuirks' in device:
					self.quirks = device['irQuirks']
				# Now unpack the part number and version values from the ID code
				partNumber = (self.idcode >> 12) & 0xffff
				version = (self.idcode >> 28) & 0xf
				return device['mfr'], partNumber, version, device['description']
		# If we found nothing, return None
		return None

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

	def annotateData(self, data: list[int, list[str]]):
		self.put(self.beginSample, self.endSample, self.outputAnnotation, data)

	def annotateBits(self, start: int, end: int, data: list[int, list[str]]):
		self.put(self.samplePositions[start][0], self.samplePositions[end][0], self.outputAnnotation, data)

	def annotateBit(self, bit: int, data: list[int, list[str]]):
		self.annotateBits(bit, bit + 1, data)

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
		# Otherwise decode the data from the state we're currently in
		else:
			assert not isinstance(value, str)
			self.handleData(action, *value)

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

	def handleData(self, state: str, data: str, samplePositions: list[list[int]]):
		'''Consume data from the JTAG decoder, splitting apart the chunks by device state

		If we're unconfigured, discard whatever we get until we've seen TLR.
		If we're awaiting ID codes, ideally the next thing to happen is that we see a DR
		dump - if we don't, go to a permanent error state.
		If we've got the ID codes for this scan chain, we can then wait to see what the IR
		topology looks like to determine how many devices and therefore ADIv5 decoders we need.
		Finally, if we're all set up, we can then feed the data we get into the decoders, having
		properly chunked it up based on which bits each decoder is actually interested in.
		'''
		if self.state == DecoderState.inactive:
			return
		# Make the sample positions and data little bit endian for sanity
		samplePositions.reverse()
		self.samplePositions = samplePositions
		if self.state == DecoderState.awaitingIDCodes:
			# If we're awaiting the ID codes from the scan chain and we see anything happen to the IR,
			# go into an error state as we can't support this (we don't yet know enough about the scan
			# chain, so this will put things into a bad state
			if state.startswith('IR'):
				self.state = DecoderState.inError
			# If we instead see a DR exchange, this must be the ID code data, so grab it and decode
			elif state == 'DR TDO':
				self.handleIDCodes(data, samplePositions)

	def handleIDCodes(self, data: str, samplePositions: list[int]):
		'''Consume a DR bitstring to be treated as a sequence of ID codes'''

		# Figure out how many devices may be on the chain, rounding down
		suspectedDevices = len(data) // 32
		devices = 0
		offset = 0
		for device in range(suspectedDevices):
			# Pick out the next 32 bits
			idcode = fromBitstring(data, begin = offset, end = offset + 32)
			# If we're done, set the number of devices properly and break out the loop
			if idcode == 0xffffffff:
				devices = device
				break
			# Otherwise, we have a device, put out the ID code in the annotations and create a device for it.
			# Decode the ID code as appropriate and display that too
			jtagDevice = JTAGDevice(drPrescan = device, idcode = idcode)
			self.annotateBits(offset, offset + 32, [A.JTAG_ITEM, [f'IDCODE: {idcode:08x}']])
			partCode = jtagDevice.decodeIDCode()
			if partCode is None:
				self.annotateBits(offset, offset + 32, [A.JTAG_FIELD, ['Unknown Device', 'Unk', 'U']])
			else:
				manufacturer, partNumber, version, description = partCode
				self.annotateBit(offset, [A.JTAG_FIELD, ['Reserved', 'Res', 'R']])
				self.annotateBits(offset + 1, offset + 12, [A.JTAG_FIELD,
					[f'Manufacturer: {manufacturer}', 'Manuf', 'M']])
				self.annotateBits(offset + 12, offset + 28, [A.JTAG_FIELD, [f'Partno: {partNumber:04x}', 'Partno', 'P']])
				self.annotateBits(offset + 28, offset + 32, [A.JTAG_FIELD, [f'Version: {version}', 'Version', 'V']])
				self.annotateBits(offset, offset + 32, [A.JTAG_NOTE, [description]])
			devices += 1
			offset += 32
			self.devices.append(jtagDevice)

		# Having consumed all the available ID codes, compute the postscan for each.
		for device in range(devices):
			self.devices[device].drPostscan = devices - device - 1
		self.state = DecoderState.countingDevices

	def __str__(self):
		return f'<ADIv5 JTAG Decoder, state {self.state}, {len(self.devices)} devices>'
