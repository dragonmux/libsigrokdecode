##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2025 Rachel Mant <git@dragonmux.network>
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
from typing import Literal
from .pd import Decoder, A

class ADIv5Target(Enum):
	ap = auto()
	dp = auto()

	@property
	def name(self) -> Literal['AP', 'DP']:
		return super().name.upper()

class ADIv5RnW(IntEnum):
	write = 0
	read = 1

	@property
	def name(self) -> Literal['READ', 'WRITE']:
		return super().name.upper()

class ADIv5Ack(IntEnum):
	invalid = 0
	ok = 1
	wait = 2
	fault = 4
	noResponse = 7

	@staticmethod
	def fromValue(ack):
		# SWD-DPs respond with 0b100 for OK
		if ack == 1:
			return ADIv5Ack.ok
		# 0b010 for WAIT
		elif ack == 2:
			return ADIv5Ack.wait
		# 0b001 for FAULT
		elif ack == 4:
			return ADIv5Ack.fault
		# 0b111 for NO-RESPONSE
		elif ack == 7:
			return ADIv5Ack.noResponse
		# And everything else is invalid
		else:
			return ADIv5Ack.invalid

	@property
	def name(self) -> Literal['INVALID', 'OK', 'WAIT', 'FAULT', 'NO-RESPONSE']:
		if self == ADIv5Ack.noResponse:
			return 'NO-RESPONSE'
		return super().name.upper()

	@property
	def annotationID(self):
		if self == ADIv5Ack.ok:
			return A.ADIV5_ACK_OK
		elif self == ADIv5Ack.wait:
			return A.ADIV5_ACK_WAIT
		elif self == ADIv5Ack.fault:
			return A.ADIV5_ACK_FAULT
		elif self == ADIv5Ack.noResponse:
			return A.ADIV5_ACK_NO_RESPONSE
		raise ValueError('Invalid ADIv5 ack value')

@unique
class ADIv5APKind(Enum):
	jtag = auto()
	com = auto()
	mem = auto()
	unknown = auto()

class ADIv5Transaction:
	'''Holder type for an ADIv5 transaction'''
	register: tuple[int, str]

	def __init__(self, begin: int, end: int, request: int, ack: int, data: int, parityOk: bool):
		# TODO: deal with parity and ack errors!
		# Extract the request bits out
		self.target = ADIv5Target.ap if (request & (1 << 1)) != 0 else ADIv5Target.dp
		self.rnw = ADIv5RnW.read if (request & (1 << 2)) != 0 else ADIv5RnW.write
		self.addr = ((request >> 3) & 3) << 2
		self.ack = ADIv5Ack.fromValue(ack)
		self.data = data
		self.position = (begin, end)

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
		match self.kind:
			case ADIv5APKind.jtag:
				return decodeJTAGAPReg
			case ADIv5APKind.mem:
				return decodeMemAPReg
			case ADIv5APKind.com:
				# These are actually defined in an entirely seperate guide
				# and we don't currently support them.
				return decodeUnknownAPReg
			case ADIv5APKind.unknown:
				return decodeUnknownAPReg

	def handleRegRead(self, reg: int, value: int):
		# If the read is for the IDR, decode the IDR's value and switch our AP kind to the result
		if reg == 0xfc:
			idr = ADIv5APIdentReg(value)
			self.kind = idr.kind

class ADIv5DP:
	'''Internal representatioon of an ADIv5 DP'''
	def __init__(self, decoder: Decoder, dp: int):
		self.decoder = decoder
		self.select = ADIv5DPSelect()
		self.dp = dp
		self.ap: dict[int, ADIv5AP] = {}
		# Default the DP to being v1 till we see the DP IDR read
		self.dpVersion = 1
		# Tag for whether this is a minmal DP and thus needs transaction merging
		self.minDP = False
		# Split transaction tracking
		self.transaction: ADIv5Transaction | None = None

	def decodeTransaction(self, transaction: ADIv5Transaction):
		# Decode and annotate what register is being accessed
		match transaction.target:
			case ADIv5Target.dp:
				self.decodeDPAccess(transaction)
			case ADIv5Target.ap:
				self.decodeAPAccess(transaction)

		# Annotate the ACK state for this access
		self.decoder.annotateSampleBits(8, 10, [transaction.ack.annotationID, [transaction.ack.name]])

		# Annotate the data phase of this access
		match transaction.rnw:
			case ADIv5RnW.read:
				self.decoder.annotateSampleBits(11, 43,
					[A.ADIV5_DATA, [f'Read: {transaction.data:08x}', 'Read', 'R']])
			case ADIv5RnW.write:
				self.decoder.annotateSampleBits(11, 43,
					[A.ADIV5_DATA, [f'Write: {transaction.data:08x}', 'Write', 'W']])

		# Check if this is an AP read access on a min-DP that therefore smeers the transaction over two
		if (transaction.target == ADIv5Target.ap and transaction.rnw == ADIv5RnW.read and
			transaction.register[1] != 'DRW'):
			# If it is, store this transaction and use it for emission in the next pass through here
			self.transaction = transaction
		elif self.transaction is not None:
			# This is a smeered transaction, emit appropriately and reset storage
			self.decoder.emit(
				self.transaction.position[0], transaction.position[1],
				f'{self.transaction.target.name}_{self.transaction.rnw.name}', self.dp,
				self.transaction.register[0], self.transaction.register[1],
				self.transaction.ack.name, transaction.data
			)
			# Feed the AP data into the AP transaction decoder
			self.ap[self.select.apsel].handleRegRead(self.transaction.register[0], transaction.data)
			# If this was a read of RDBUFF we're done with the smeered transactions
			if transaction.target == ADIv5Target.dp and transaction.register[1] == 'RDBUFF':
				self.transaction = None
			# Otherwise this was another AP access most likely so store and deal with in the next cycle
			else:
				self.transaction = transaction
		else:
			# Emit the transaction into the next decoder up the stack now we know what's going on here
			self.decoder.emit(
				transaction.position[0], transaction.position[1],
				f'{transaction.target.name}_{transaction.rnw.name}', self.dp, transaction.register[0],
				transaction.register[1], transaction.ack.name, transaction.data
			)

	def decodeDPReg(self, transaction: ADIv5Transaction):
		rnw = transaction.rnw
		reg = transaction.addr
		bank = self.select.dpBank

		# If it's a read for register 0, regardless of bank, it's DPIDR
		if rnw == ADIv5RnW.read and reg == 0:
			# Extract the DP version real quick and stuff it in dpVersion
			self.dpVersion = (transaction.data >> 12) & 0xf
			# Likewise the MinDP bit
			self.minDP = (transaction.data & (1 << 16)) != 0
			return 'DPIDR'
		# If it's a write for register 0, regardless of bank, it's ABORT
		if rnw == ADIv5RnW.write and reg == 0:
			return 'ABORT'
		# If it's a read for register 8, regardless of bank, it's RESEND
		if rnw == ADIv5RnW.read and reg == 8:
			return 'RESEND'
		# If it's a write for register 8, regardless of bank, it's SELECT
		if rnw == ADIv5RnW.write and reg == 8:
			return 'SELECT'
		# If it's a read for register 12, regardless of bank, it's RDBUFF
		elif rnw == ADIv5RnW.read and reg == 12:
			return 'RDBUFF'

		# Having dealt with the registers that appear on all banks regardless of version,
		# deal with registers that only appear as register 4 regardless of version
		if reg == 4:
			match bank:
				case 0:
					return 'CTRL/STAT'
				case 1:
					return 'DLCR'

		# Deal with DPv2+ registers that appear on all banks
		if self.dpVersion >= 2 and rnw == ADIv5RnW.write and reg == 12:
			return 'TARGETSEL'

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

	def decodeDPAccess(self, transaction: ADIv5Transaction):
		# Decode the register being requested
		register = self.decodeDPReg(transaction)
		self.decoder.annotateSampleBits(0, 7, [A.ADIV5_REGISTER, [register]])
		# If it's a write to the select register, also pass that to our internal notion of its state
		if register == 'SELECT' and transaction.rnw == ADIv5RnW.write:
			self.select.changeValue(transaction.data)
		# Store the decoded register for use in further decoding
		transaction.register = ((self.select.dpBank << 4) | transaction.addr, register)

	def decodeAPAccess(self, transaction: ADIv5Transaction):
		# Get the AP associated with this transaction
		ap = self.ap.get(self.select.apsel)
		if ap is None:
			ap = self.ap[self.select.apsel] = ADIv5AP(self.select.apsel)
		# Now grab the register name for this AP
		address = (self.select.apBank << 4) | transaction.addr
		register = ap.regDecoder(transaction.rnw, address)
		self.decoder.annotateSampleBits(0, 7, [A.ADIV5_REGISTER, [register]])
		# Store the decoded register for use in further decoding
		transaction.register = (address, register)

class SWDDevices:
	def __init__(self, decoder: Decoder):
		self.decoder = decoder
		self.selectedDP = 0
		self.dps = dict[int, ADIv5DP]()
		# It's impossible for a SWD setup to be less than DPv1
		self.dpVersion = 1

	def reset(self):
		self.selectedDP = 0
		self.dps.clear()
		self.dpVersion = 1

	def transaction(self, begin: int, end: int, request: int, ack: int, data: int, parityOk: bool):
		# Turn the request into a transaction
		transaction = ADIv5Transaction(begin, end, request, ack, data, parityOk)

		# Identify if this is a TARGETSEL sequence
		if (self.dpVersion >= 2 and transaction.ack == ADIv5Ack.noResponse and
			transaction.rnw == ADIv5RnW.write and transaction.addr == 12):
			# Extract which DP is being selected from the request
			self.selectedDP = (transaction.data >> 28) & 0xf
		# If this is a DP IDR read instead, grab the version and stuff it in dpVersion
		if (transaction.ack == ADIv5Ack.ok and transaction.rnw == ADIv5RnW.read and
			transaction.addr == 0):
			self.dpVersion = (transaction.data >> 12) & 0xf

		# Setup for decoding
		dpIndex = self.selectedDP
		# If this DP hasn't yet been seen before (say, because it only just got selected), make a new one for it
		if dpIndex not in self.dps:
			self.dps[dpIndex] = ADIv5DP(self.decoder, dpIndex)

		# Annotate the request as a command
		target = transaction.target.name
		accessType = 'read' if transaction.rnw == ADIv5RnW.read else 'write'
		self.decoder.annotateSampleBits(0, 44, [A.SWD_COMMAND, [f'DP{dpIndex} {target} {accessType}']])

		# Process and decode the transaction
		self.dps[dpIndex].decodeTransaction(transaction)
