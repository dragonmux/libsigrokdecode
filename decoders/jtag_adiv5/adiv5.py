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

	@property
	def name(self):
		return super().name.upper()

	@property
	def annotationID(self):
		if self == ADIv5Ack.ok:
			return A.ADIV5_ACK_OK
		elif self == ADIv5Ack.wait:
			return A.ADIV5_ACK_WAIT
		elif self == ADIv5Ack.fault:
			return A.ADIV5_ACK_FAULT
		raise ValueError('Invalid ADIv5 ack value')

@unique
class ADIv5APKind(Enum):
	jtag = auto()
	com = auto()
	mem = auto()
	unknown = auto()

class ADIv5Transaction:
	register: tuple[int, str]

	def __init__(self, dataIn: int, dataOut: int, state: ADIv5State):
		self.state = state
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

class ADIv5DPSelect:
	'''Internal representation of the state of the DP SELECT register'''
	def __init__(self):
		self.apsel = 0
		self.apBank = 0
		self.dpBank = 0

	def changeValue(self, select: int):
		'''Decode a write to the SELECT register to get the new value'''
		self.apsel = select >> 24
		self.apBank = (select >> 4) & 0xf
		self.dpBank = select & 0xf

class ADIv5APIdentReg:
	'''Internal representation of an AP's IDR'''
	def __init__(self, value: int):
		# Exctract the AP class and type from the IDR value
		apClass = (value >> 13) & 0xf
		apType = value & 0xf

		# Decode them to the AP kind
		if apType == 0x0 and apClass == 0x0:
			self.kind = ADIv5APKind.jtag
		elif apType == 0x0 and apClass == 0x1:
			self.kind = ADIv5APKind.com
		elif 0x1 <= apType <= 0x8 and apClass == 0x8:
			self.kind = ADIv5APKind.mem
		else:
			self.kind = ADIv5APKind.unknown

		# Also grab and store the other AP ID metadata
		self.revision = value >> 28
		self.designer = (value >> 17) & 0x7ff
		self.variant = (value >> 4) & 0xf

	def __str__(self):
		return f'<AP IDR, kind = {self.kind}, designer: {self.designer:03x}, rev: {self.revision}, var: {self.variant}>'

def decodeUnknownAPReg(rnw: ADIv5RnW, addr: int):
	'''Decodes AP register accesses for an unknown type of AP'''
	# IDR is read-only
	if rnw == ADIv5RnW.read and addr == 0xfc:
		return 'IDR'
	return f'INVALID ({addr:02x})'

def decodeJTAGAPReg(rnw: ADIv5RnW, addr: int):
	'''Decodes AP register accesses for JTAG-APs'''
	if addr == 0x00:
		return 'CSW'
	elif addr == 0x04:
		return 'PSEL'
	elif addr == 0x08:
		return 'PSTA'
	elif 0x10 <= addr <= 0x1c:
		reg = (addr >> 2) & 3
		return f'BRFIFO{reg + 1}'
	# Once we've exhausted the standard JTAG-AP regs, defer to the unknwon AP type decoder
	return decodeUnknownAPReg(rnw, addr)

def decodeMemAPReg(rnw: ADIv5RnW, addr: int):
	'''Decodes AP register accesses for MEM-APs'''
	if addr == 0x00:
		return 'CSW'
	elif addr == 0x04:
		return 'TAR (low)'
	elif addr == 0x08:
		return 'TAR (high)'
	elif addr == 0x0c:
		return 'DRW'
	elif 0x10 < addr < 0x1c:
		reg = (addr >> 2) & 3
		return f'BD{reg}'
	elif addr == 0x20:
		return 'MBT'
	elif addr == 0x30:
		return 'T0TR'
	elif rnw == ADIv5RnW.read:
		if addr == 0xe0:
			return 'CFG1'
		elif addr == 0xf0:
			return 'BASE (high)'
		elif addr == 0xf4:
			return 'CFG'
		elif addr == 0xf8:
			return 'BASE (low)'
	# Once we've exhausted the standard MEM-AP regs, defer to the unknwon AP type decoder
	return decodeUnknownAPReg(rnw, addr)

class ADIv5AP:
	'''Internal representation of an ADIv5 AP'''
	def __init__(self, apsel: int):
		self.apsel = apsel
		self.kind = ADIv5APKind.unknown

	@property
	def regDecoder(self):
		if self.kind == ADIv5APKind.jtag:
			return decodeJTAGAPReg
		elif self.kind == ADIv5APKind.mem:
			return decodeMemAPReg
		elif self.kind == ADIv5APKind.com:
			# These are actually defined in an entirely seperate guide
			# and we don't currently support them.
			return decodeUnknownAPReg
		elif self.kind == ADIv5APKind.unknown:
			return decodeUnknownAPReg

	def handleRegRead(self, addr: int, bank: int, value: int):
		reg = (bank << 4) | addr
		# If the read is for the IDR, decode the IDR's value and switch our AP kind to the result
		if reg == 0xfc:
			idr = ADIv5APIdentReg(value)
			self.kind = idr.kind

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
		self.dpVersion = (device.idcode >> 12) & 0xf
		self.transactionNumber = 0
		self.transaction: ADIv5Transaction | None = None
		self.select = ADIv5DPSelect()
		self.ap: dict[int, ADIv5AP] = {}

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
		transaction = ADIv5Transaction(dataIn, dataOut, self.state)
		# With that decoded, annotate the request as a command
		deviceIndex = self.device.deviceIndex
		dpIndex: int = self.device.dpIndex
		target = self.state.target
		if self.state == ADIv5State.apAccess:
			target = f'AP{self.select.apsel} {target}'
		accessType = 'read' if transaction.rnw == ADIv5RnW.read else 'write'
		self.device.decoder.annotateBits(begin, end,
			[A.JTAG_COMMAND, [f'TAP {deviceIndex}: DP{dpIndex} {target} {accessType}']])

		# Handle requests to the ABORT register as those are nice and tidy
		if self.state == ADIv5State.abort:
			self.decodeAbort(begin, end, transaction)
			return

		# Normal transactions are lagged over two requests, w/ the new request having the status of the previous.
		self.decodeResponse(begin, end, transaction)
		# Having dealt with the previous transaction, now decode the current
		# Start by annotating if this is a read or a write
		if transaction.rnw == ADIv5RnW.read:
			self.device.decoder.annotateBit(begin, [A.ADIV5_READ, ['Read', 'RD', 'R']])
		elif transaction.rnw == ADIv5RnW.write:
			self.device.decoder.annotateBit(begin, [A.ADIV5_WRITE, ['Write', 'WR', 'W']])
			self.device.decoder.annotateBits(begin + 3, end, [A.ADIV5_REQUEST, [f'{transaction.request:08x}']])
		# Now handle AP vs DP details
		if self.state == ADIv5State.dpAccess:
			self.decodeDPAccess(begin, end, transaction)
		elif self.state == ADIv5State.apAccess:
			self.decodeAPAccess(begin, end, transaction)

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
		# And emit it to the next decoder in the stack

	def decodeResponse(self, begin: int, end: int, transaction: ADIv5Transaction):
		# Determine the state of the previous transaction and annotate it to the response track
		if self.transaction is not None:
			# Only decode the response if we've got a previous transaction (otherwise we don't have enough
			# information to know how to understand the response we're getting)
			self.device.decoder.annotateBits(begin, begin + 2, [transaction.ack.annotationID, [transaction.ack.name]])
			if self.transaction.rnw == ADIv5RnW.read:
				self.device.decoder.annotateBits(begin + 3, end,
					[A.ADIV5_RESULT, [f'Read: {transaction.response:08x}', 'Read', 'R']])
				# If this response is for an AP read transaction, feed it into the AP handler
				if transaction.ack == ADIv5Ack.ok and self.transaction.state == ADIv5State.apAccess:
					self.ap[self.select.apsel].handleRegRead(self.transaction.addr, self.select.apBank,
						transaction.response)
			# Having processed the previous transaction's result, increment the number and store this transaction
			self.transactionNumber += 1
		self.transaction = transaction

	def decodeDPReg(self, transaction: ADIv5Transaction):
		rnw = transaction.rnw
		reg = transaction.addr
		# DPv0's only have bank 0 registers, so ignore the bank value on them
		bank = 0 if self.dpVersion == 0 else self.select.dpBank

		# If it's a write for register 8, regardless of bank, it's SELECT
		if rnw == ADIv5RnW.write and reg == 8:
			return 'SELECT'
		# If it's a read for register 12, regardless of bank, it's RDBUFF
		elif rnw == ADIv5RnW.read and reg == 12:
			return 'RDBUFF'

		# Having dealt with the registers that appear on all banks regardless of version,
		# deal with the last registers for DPv0 and that only appear on bank 0
		if bank == 0:
			if reg == 4:
				return 'CTRL/STAT'
			if self.dpVersion == 0 and rnw == ADIv5RnW.read and reg == 8:
				return 'SELECT'

		# Now deal with DPv1+ all-banks registers
		if self.dpVersion >= 1 and rnw == ADIv5RnW.read and reg == 0:
			return 'DPIDR'

		# Now deal with DPv1+ bank-specific registers
		if self.dpVersion >= 1 and bank == 1 and reg == 4:
			return 'DLCR'

		# Now deal with DPv2+ bank-specific registers
		if self.dpVersion >= 2 and rnw == ADIv5RnW.read and reg == 4:
			if bank == 2:
				return 'TARGETID'
			elif bank == 3:
				return 'DLPIDR'
			elif bank == 4:
				return 'EVENTSTAT'

		# Having exhausted all other possible registers, deal with invalid ones
		return 'INVALID'

	def decodeDPAccess(self, begin: int, end: int, transaction: ADIv5Transaction):
		# Decode the register being requested
		register = self.decodeDPReg(transaction)
		self.device.decoder.annotateBits(begin + 1, begin + 2,
			[A.ADIV5_REGISTER, [register]])
		# If it's a write to the select register, also pass that to our internal notion of its state
		if register == 'SELECT' and transaction.rnw == ADIv5RnW.write:
			self.select.changeValue(transaction.request)
		# Store the decoded register for later access when we have the associated ack
		transaction.register = ((self.select.dpBank << 4) | transaction.addr, register)

	def decodeAPAccess(self, begin: int, end: int, transaction: ADIv5Transaction):
		# Get the AP associated with this transaction
		ap = self.ap.get(self.select.apsel)
		if ap is None:
			ap = self.ap[self.select.apsel] = ADIv5AP(self.select.apsel)
		# Now grab the register name for this AP
		address = (self.select.apBank << 4) | transaction.addr
		register = ap.regDecoder(transaction.rnw, address)
		self.device.decoder.annotateBits(begin + 1, begin + 2,
			[A.ADIV5_REGISTER, [register]])
		# Store the decoded register for later access when we have the associated ack
		transaction.register = (address, register)
