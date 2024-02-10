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
class DecoderState(Enum):
	inactive = auto()
	idle = auto()
	awaitingIDCodes = auto()
	countingDevices = auto()
	awaitingReset = auto()
	awaitingIR = auto()
	awaitingDR = auto()
	inError = auto()

def fromBitstring(bits: str, begin: int, end: int = -1) -> int:
	'''Grab a chunk from a big bit endian bitstring, and decode it to an integer

	`begin` is the first logical bit desired, `end` is the last forming
	an interval of the form [begin:end)
	'''
	length = len(bits)
	if end == -1:
		end = begin + 1
	substr = bits[length - end:length - begin]
	return int(substr, base = 2)

class JTAGDevice:
	idcode: int
	currentInsn: int

	drPrescan: int
	drPostscan: int

	irLength: int
	irPrescan: int
	irPostscan: int

	def __init__(self, decoder: 'Decoder', drPrescan: int, idcode: int):
		self.decoder = decoder
		self.tapDecoder = None
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

	@property
	def deviceIndex(self):
		return self.drPrescan

	@property
	def irBegin(self):
		return self.irPrescan

	@property
	def irEnd(self):
		return self.irPrescan + self.irLength - 1

	@property
	def drLength(self):
		if self.tapDecoder is None:
			return None
		return self.tapDecoder.drLength

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

	def setupDecoder(self):
		# If this is an ADIv5 TAP, set up the ADIv5 decoder for it
		if self.isADIv5:
			from .adiv5 import ADIv5Decoder
			self.tapDecoder = ADIv5Decoder(self)

	def irChange(self, newInsn: int):
		# Store the new instruction value
		self.currentInsn = newInsn
		# If there is no decoder for this TAP, do what we can
		if self.tapDecoder is None:
			# If the instruction is the bypass bit sequence, display that at least
			if newInsn == (1 << self.irLength) - 1:
				self.decoder.annotateBits(self.irBegin, self.irEnd,
					[A.JTAG_COMMAND, [f'TAP {self.deviceIndex}: BYPASS', 'BYPASS']])
			# Otherwise display it as an unknown instruction
			else:
				self.decoder.annotateBits(self.irBegin, self.irEnd,
					[A.JTAG_COMMAND, [f'TAP {self.deviceIndex}: UNKNOWN', 'UNKNOWN']])
		# Otherwise, if we've got a TAP decoder, ask it to decode the instruction and annotate
		else:
			self.tapDecoder.decodeInsn()

	def __str__(self):
		return f'<JTAGDevice {self.deviceIndex}: {self.idcode:08x}>'

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

	def reset(self):
		self.state = DecoderState.inactive
		self.irSampleData = None
		self.devices.clear()

	def start(self):
		self.reset()
		self.outputAnnotation = self.register(srd.OUTPUT_ANN)

	def annotateData(self, data: list[int, list[str]]):
		self.put(self.beginSample, self.endSample, self.outputAnnotation, data)

	def annotateBits(self, begin: int, end: int, data: list[int | list[str]]):
		self.put(self.samplePositions[begin][0], self.samplePositions[end][1], self.outputAnnotation, data)

	def annotateBit(self, bit: int, data: list[int | list[str]]):
		self.annotateBits(bit, bit, data)

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
			self.devices.clear()
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
			# assumine it's IR scanout, but store the scanned out data to one side to handle after
			# the ID codes
			if state == 'IR TDO' and self.irSampleData is None:
				self.irSamplePositions = samplePositions
				self.irSampleData = data
				self.state = DecoderState.awaitingReset
			# If we instead see a DR exchange, this must be the ID code data, so grab it and decode
			elif state == 'DR TDO':
				self.handleIDCodes(data)
				# If we've stuffed IR data to one side previously, and now we understand the ID codes,
				# process the IR readout so we can get done setting up
				if self.irSampleData is not None:
					self.samplePositions = self.irSamplePositions
					self.determineIRLengths(self.irSampleData)
					self.irSampleData = None
					del self.irSamplePositions
		elif self.state == DecoderState.countingDevices:
			# If we now need to determine the IR topology so we can decode the data, check if the next
			# thing we see is an IR readout - if it is, decode it
			if state == 'IR TDO':
				self.determineIRLengths(data)
			# If we see activity on the DR while we wait, something's gone very wrong, so bail
			elif state.startswith('DR'):
				self.state = DecoderState.inError
		elif self.state == DecoderState.awaitingIR:
			# If we're awaiting an IR change, grab the value being loaded in to reconfigure the
			# ADIv5 decoders for the new action/state
			if state == 'IR TDI':
				self.handleIRChange(data)
		elif self.state == DecoderState.awaitingDR:
			# If we're awaiting a DR change, grab the TDI data and store it -
			# the JTAG decoder hands us first the in data then out data.
			# Thankfully, the sample positions for both are identical
			if state == 'DR TDI':
				self.dataIn = data
			elif state == 'DR TDO':
				# Grab the in data and verify that the lengths match
				dataIn = self.dataIn
				del self.dataIn
				if len(dataIn) != len(data):
					self.annotateBits(0, -1, [A.JTAG_NOTE, ['Mismatched TDI and TDO lengths']])
					self.state = DecoderState.inError
					return
				# If everything checks out, proceed
				self.handleDRChange(dataLength = len(data), dataIn = dataIn, dataOut = data)

	def handleIDCodes(self, data: str):
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
			jtagDevice = JTAGDevice(decoder = self, drPrescan = device, idcode = idcode)
			self.annotateBits(offset, offset + 31, [A.JTAG_ITEM, [f'IDCODE: {idcode:08x}', 'IDCODE', 'I']])
			partCode = jtagDevice.decodeIDCode()
			if partCode is None:
				self.annotateBits(offset, offset + 31, [A.JTAG_FIELD, ['Unknown Device', 'Unk', 'U']])
			else:
				manufacturer, partNumber, version, description = partCode
				self.annotateBit(offset, [A.JTAG_FIELD, ['Reserved', 'Res', 'R']])
				self.annotateBits(offset + 1, offset + 11, [A.JTAG_FIELD,
					[f'Manufacturer: {manufacturer}', 'Manuf', 'M']])
				self.annotateBits(offset + 12, offset + 27, [A.JTAG_FIELD, [f'Partno: {partNumber:04x}', 'Partno', 'P']])
				self.annotateBits(offset + 28, offset + 31, [A.JTAG_FIELD, [f'Version: {version}', 'Version', 'V']])
				self.annotateBits(offset, offset + 31, [A.JTAG_NOTE, [description]])
			devices += 1
			offset += 32
			self.devices.append(jtagDevice)

		# Having consumed all the available ID codes, compute the postscan for each.
		for device in range(devices):
			self.devices[device].drPostscan = devices - device - 1
		self.state = DecoderState.countingDevices

	def determineIRLengths(self, data: str):
		'''Consume an IR bitstring to detemine the IR lengths and topology'''

		# Get any quirks we may have for the first device
		prescan = 0
		device = 0
		irLength = 0
		irQuirks = self.devices[device].quirks

		# Loop through each of the bits in the bitstring, counting how long the IRs for each device is
		for offset in range(len(data)):
			nextBit = fromBitstring(data, offset)
			# If we have quirks, validate the bit against the expected IR
			if irQuirks is not None and ((irQuirks['value'] >> irLength) & 1) == nextBit:
				self.annotateBits(prescan, offset, [A.JTAG_NOTE, ['Error decoding IR']])
				self.state = DecoderState.inError
				return
			#  IEEE 1149.1 requires the first bit to be a 1, but not all devices conform
			if irLength == 0 and not nextBit:
				self.annotateBit(prescan, [A.JTAG_NOTE, ['Buggy IR[0]']])

			# If we got here, we've got a good IR bit
			irLength += 1

			# Now, if we do not have quirks in play and this was a 1 bit and we're not reading the first
			# bit of the current IR, or if we've now read sufficient bits for the quirk, we've got a complete IR
			if ((irQuirks is None and nextBit and irLength > 1) or
				(irQuirks is not None and irLength == irQuirks['length'])):
				# If we're not in quirks mode and the IR length is now 2 (2 1-bit in a row read), we're done
				if irQuirks is None and irLength == 2:
					break
				# If we've consumed all the devices on the chain and there's still IRs data to consume
				# then something is terribly wrong
				if device == len(self.devices):
					self.annotateBits(prescan, len(data) - 1, [A.JTAG_NOTE, ['Error decoding IR']])
					self.state = DecoderState.inError
					return

				# If we're reading using quirks, we'll read exactly the right number of bits,
				# if not then we overrun by 1 for the device. Calculate the adjustment.
				overrun = 1 if irQuirks is None else 0
				deviceIR = irLength - overrun
				self.annotateBits(prescan, prescan + deviceIR - 1, [A.JTAG_FIELD, [f'{deviceIR} bit IR']])

				# Set up the IR fields for the device and set up for the next
				jtagDevice = self.devices[device]
				jtagDevice.irLength = deviceIR
				jtagDevice.irPrescan = prescan
				jtagDevice.setupDecoder()
				# During the scan-out process, the device will be put into BYPASS
				jtagDevice.irChange((1 << deviceIR) - 1)
				prescan += deviceIR
				device += 1
				irLength = overrun
				# Grab the quirks for the next device that should be on the chain
				if device < len(self.devices):
					irQuirks = self.devices[device].quirks
				else:
					irQuirks = None

		# Loop through all the devices calculating their IR postscan values now we're done
		postscan = 0
		for jtagDevice in reversed(self.devices):
			jtagDevice.irPostscan = postscan
			postscan += jtagDevice.irLength
		# Now we're all set up, switch into our idle state
		self.state = DecoderState.idle

	def handleIRChange(self, data: str):
		'''Consume a new IR state bitstring to determine what the next DR transaction means'''
		# Loop through all the known devices, updating them with their new IR values
		for device in self.devices:
			begin = device.irPrescan
			end = begin + device.irLength
			ir = fromBitstring(data, begin, end)
			self.annotateBits(begin, end - 1, [A.JTAG_ITEM, [f'IR: {ir:0{(device.irLength + 3) // 4}x}', 'IR']])
			device.irChange(ir)
		self.state = DecoderState.idle

	def handleDRChange(self, dataLength: int, dataIn: str, dataOut: str):
		'''Consume a pair of DR bitstrings and decode what they mean to the device converstation'''
		# Start by determining the known DR lengths for all devices
		drLengths = [device.drLength for device in self.devices]
		# Count unknowns - if there's more than 1, we can't do anything with this DR data
		drUnknowns = drLengths.count(None)
		if drUnknowns > 1:
			# Annotate the bits as being indeterminate, and go back to idle
			self.annotateBits(0, -1, [A.JTAG_NOTE, ['Too many unknown DR lengths', 'UNKNOWN']])
			self.state = DecoderState.idle
			return
		elif drUnknowns == 1:
			# Determine what the length of the unknown DR must be and assign it into the lengths list
			unknownLength = dataLength - sum(0 if length is None else length for length in drLengths)
			drLengths[drLengths.index(None)] = unknownLength

		offset = 0
		# Loop through all the known devices, chunking up the DR appropriately and feeding them with their chunks
		for deviceIndex, device in enumerate(self.devices):
			drLength = drLengths[deviceIndex]
			assert drLength is not None
			# Extract this TAP's DR values and feed them into the decoder
			begin = offset
			end = offset + drLength
			drIn = fromBitstring(dataIn, begin, end)
			drOut = fromBitstring(dataOut, begin, end)
			self.annotateBits(begin, end - 1, [A.JTAG_ITEM, ['DR']])
			offset += drLength

		self.state = DecoderState.idle

	def __str__(self):
		return f'<ADIv5 JTAG Decoder, state {self.state}, {len(self.devices)} devices>'
