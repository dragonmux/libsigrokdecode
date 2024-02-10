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

from enum import Enum, IntEnum, unique, auto
from .pd import JTAGDevice, A

@unique
class ADIv5State(Enum):
	idle = auto()
	abort = auto()
	dpAccess = auto()
	apAccess = auto()
	inError = auto()

	@property
	def target(self):
		if self == ADIv5State.abort:
			return 'ABORT'
		elif self == ADIv5State.dpAccess:
			return 'DP'
		elif self == ADIv5State.apAccess:
			return 'AP'
		else:
			return 'UNKNOWN'

class ADIv5RnW(IntEnum):
	write = 0
	read = 1

class ADIv5Ack(IntEnum):
	ok = 1
	wait = 2
	fault = 4

class ADIv5Transaction:
	def __init__(self, dataIn: int, dataOut: int):
		self.rnw = ADIv5RnW(dataIn & 1)
		self.addr = ((dataIn >> 1) & 3) << 2
		self.request = dataIn >> 3
		self.ack = dataOut & 7
		self.response = dataOut >> 3

	@property
	def ack(self):
		return self._ack

	@ack.setter
	def ack(self, ack):
		# JTAG-DPs respond with 2 for OK
		if ack == 2:
			self._ack = ADIv5Ack.ok
		# 1 for WAIT
		elif ack == 1:
			self._ack = ADIv5Ack.wait
		# And everything else is a fault condition
		else:
			self._ack = ADIv5Ack.fault

class ADIv5Decoder:
	instructions = {
		0x8: ('ABORT', ADIv5State.abort),
		0xa: ('DPACC', ADIv5State.dpAccess),
		0xb: ('APACC', ADIv5State.apAccess),
		0xe: ('IDCODE', ADIv5State.idle),
		0xf: ('BYPASS', ADIv5State.idle),
	}
	state: ADIv5State

	def __init__(self, device: 'JTAGDevice'):
		self.device = device
		self.state = ADIv5State.idle

	@property
	def instruction(self):
		# 8-bit instructions only extend the 4-bit ones with the high bits set for all valid ones
		# so truncate them back down to 4-bit for this having verified they're in range
		if self.device.irLength == 8 and self.device.currentInsn & 0xf0 != 0xf0:
			return 0
		else:
			return self.device.currentInsn & 0xf

	@property
	def drLength(self):
		'''Convert the current instruction over to its associated DR length'''
		insn = self.instruction
		if insn == 0xf:
			return 1
		elif insn == 0xe:
			return 32
		elif insn in (0x8, 0xa, 0xb):
			return 35
		# Return None if we don't know what the DR length could be
		return None

	def decodeInsn(self):
		# Look the instruction up, convert it to a decoder state and annotate the bits
		name, self.state = ADIv5Decoder.instructions.get(self.instruction, ('UNKNOWN', ADIv5State.inError))
		self.device.decoder.annotateBits(self.device.irBegin, self.device.irEnd,
			[A.JTAG_COMMAND, [f'TAP {self.device.deviceIndex}: {name}', name]])

	def decodeData(self, begin: int, end: int, dataIn: int, dataOut: int):
		# If we're in an idle state, do nothing
		if self.state == ADIv5State.idle:
			return

		# Annotate the bits to display the hex values
		hexLength: int = (self.drLength + 3) // 4
		insnName, _ = ADIv5Decoder.instructions.get(self.instruction, ('UNKNOWN', ADIv5State.inError))
		self.device.decoder.annotateBits(begin, end,
			[A.JTAG_ITEM, [
				f'{insnName} Data - In: {dataIn:0{hexLength}x}, Out: {dataOut:0{hexLength}x}',
				f'{insnName} Data',
				'Data'
			]]
		)

		# Turn the request into a transaction
		transaction = ADIv5Transaction(dataIn, dataOut)
		# With that decoded, annotate the request as a command
		deviceIndex = self.device.deviceIndex
		dpIndex: int = self.device.dpIndex
		target = self.state.target
		accessType = 'read' if transaction.rnw == ADIv5RnW.read else 'write'
		self.device.decoder.annotateBits(begin, end,
			[A.JTAG_COMMAND, [f'TAP {deviceIndex}: DP{dpIndex} {target} {accessType}']])

		if self.state == ADIv5State.abort:
			self.decodeAbort(begin, end, transaction)

	def decodeAbort(self, begin: int, end: int, transaction: ADIv5Transaction):
		# If we've decoded a request to write the abort register, it's a bad request
		# The address bits should also always be 0 to select the correct register
		if transaction.rnw == ADIv5RnW.read or transaction.addr != 0:
			self.device.decoder.annotateBits(begin, end, [A.ADIV5_REQUEST, ['Invalid request']])
			return
		# Emit annotations for the ABORT write onto the request track
		self.device.decoder.annotateBit(begin, [A.ADIV5_WRITE, ['Write', 'WR', 'W']])
		self.device.decoder.annotateBits(begin + 1, begin + 2, [A.ADIV5_REGISTER, ['ABORT', 'ABT']])
		self.device.decoder.annotateBits(begin + 3, end, [A.ADIV5_REQUEST, [f'{transaction.request:08x}']])
