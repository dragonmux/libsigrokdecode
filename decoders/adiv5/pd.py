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
from abc import ABCMeta, abstractmethod
from enum import Enum, unique, auto
from typing import Literal

__all__ = ['Decoder']

class Annotations:
	'''Annotation and binary output classes.'''
	(
		TRANS_EVEN, TRANS_ODD,
		READ, WRITE, OK, WAIT, FAULT, NO_RESPONSE
	) = range(8)
A = Annotations

ADIv5Op = Literal['DP_READ', 'DP_WRITE', 'AP_READ', 'AP_WRITE']
ADIv5AckLiteral = Literal['OK', 'WAIT', 'FAULT', 'NO-RESPONSE']

@unique
class ADIv5Target(Enum):
	ap = auto()
	dp = auto()

@unique
class ADIv5RnW(Enum):
	write = auto()
	read = auto()

@unique
class ADIv5Ack(Enum):
	ok = auto()
	wait = auto()
	fault = auto()
	noResult = auto()

@unique
class ADIv5APKind(Enum):
	jtag = auto()
	com = auto()
	mem = auto()
	unknown = auto()

class ADIv5Transaction:
	def __init__(self, op: ADIv5Op, dp: int, addr: int, reg: str, ack: ADIv5AckLiteral, data: int):
		target, rnw = op.split('_')
		self.target = ADIv5Target.ap if target == 'AP' else ADIv5Target.dp
		self.rnw = ADIv5RnW.read if rnw == 'READ' else ADIv5RnW.write
		self.dp = dp
		self.register = addr, reg
		self.data = data

		if ack == 'OK':
			self.ack = ADIv5Ack.ok
		elif ack == 'WAIT':
			self.ack = ADIv5Ack.wait
		elif ack == 'FAULT':
			self.ack = ADIv5Ack.fault
		elif ack == 'NO-RESPONSE':
			self.ack = ADIv5Ack.noResult
		else:
			raise ValueError('Invalid ACK value given')

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

class ADIv5AP(metaclass = ABCMeta):
	'''This serves as a base type for all AP variants'''
	@staticmethod
	def fromID(value: int):
		'''Construct a suitable AP instance from an ID register value'''
		ident = ADIv5APIdentReg(value)
		if ident.kind == ADIv5APKind.jtag:
			return ADIv5JTAGAP(ident)

	@abstractmethod
	def __init__(self, ident: ADIv5APIdentReg):
		self.idr = ident

	@abstractmethod
	def decodeTransaction(self, transaction: ADIv5Transaction):
		reg = transaction.register[1]
		if reg == 'IDR':
			self.idr = ADIv5APIdentReg(transaction.data)
		else:
			raise ValueError('Invalid register passed to AP instance')

class ADIv5JTAGAP(ADIv5AP):
	def __init__(self, ident: ADIv5APIdentReg):
		super().__init__(ident)
		self.csw = 0
		self.psel = 0
		self.psta = 0
		self.brfifo = tuple(0, 0, 0, 0)

	def decodeTransaction(self, transaction: ADIv5Transaction):
		addr, reg = transaction.register
		if reg == 'CSW':
			self.csw = transaction.data
		elif reg == 'PSEL':
			self.psel = transaction.data
		elif reg == 'PSTA':
			self.psta = transaction.data
		elif reg.startswith('BRFIFO'):
			index = (addr >> 2) & 3
			self.brfifo[index] = transaction.data
		else:
			super().decodeTransaction(transaction)

class ADIV5MemAP(ADIv5AP):
	def __init__(self, ident: ADIv5APIdentReg):
		super().__init__(ident)
		self.csw = 0
		self.tar = 0
		self.drw = 0
		self.bd = tuple(0, 0, 0, 0)
		self.mbt = 0
		self.t0tr = 0
		self.cfg1 = 0
		self.cfg = 0
		self.base = 0

	def decodeTransaction(self, transaction: ADIv5Transaction):
		addr, reg = transaction.register
		if reg == 'CSW':
			self.csw = transaction.data
		elif reg.startswith('TAR'):
			# If it's the low half, discard the low 32 bits and replace them
			if addr == 0x04:
				self.tar &= 0xffffffff_00000000
				self.tar |= transaction.data
			# If it's the high half however, discard the upper 32 bits and replace them instead
			else:
				self.tar &= 0x00000000_ffffffff
				self.tar |= (transaction.data << 32)
		elif reg == 'DRW':
			self.drw = transaction.data
		elif reg.startswith('BD'):
			index = (addr >> 2) & 3
			self.bd[index] = transaction.data
		elif reg == 'MBT':
			self.mbt = transaction.data
		elif reg == 'T0TR':
			self.t0tr = transaction.data
		elif reg == 'CFG1':
			self.cfg1 = transaction.data
		elif reg == 'CFG':
			self.cfg = transaction.data
		elif reg.startswith('BASE'):
			# If it's the low half, discard the low 32 bits and replace them
			if addr == 0xf8:
				self.base &= 0xffffffff_00000000
				self.base |= transaction.data
			# If it's the high half however, discard the upper 32 bits and replace them instead
			else:
				self.base &= 0x00000000_ffffffff
				self.base |= (transaction.data << 32)
		else:
			super().decodeTransaction(transaction)

class ADIv5DPCtrlStat:
	pass

class ADIv5DPID:
	pass

class ADIv5DPTargetID:
	pass

class ADIv5DPSelect:
	'''Internal representation of the state of the DP SELECT register (NB, we only care about the AP selected)'''
	def __init__(self):
		self.currentAP = 0

	def changeValue(self, select: int):
		'''Decode a write to the SELECT register to get the new value'''
		self.currentAP = select >> 24

class ADIv5DP:
	def __init__(self):
		self.abort = 0
		self.ctrlstat = 0
		self.select = ADIv5DPSelect()
		self.rdbuff = 0
		self.dpidr = 0
		self.dlcr = 0
		self.targetid = 0
		self.dlpidr = 0
		self.eventstat = 0
		self.ap: dict[int, ADIv5AP] = {}

	def decodeTransaction(self, transaction: ADIv5Transaction):
		# If the transaction is for the DP, process the data into current register state
		if transaction.target == ADIv5Target.dp:
			reg = transaction.register[1]
			if reg == 'ABORT':
				self.abort = transaction.data
			elif reg == 'CTRL/STAT':
				self.ctrlstat = transaction.data
			elif reg == 'SELECT':
				self.select.changeValue(transaction.data)
			elif reg == 'RDBUFF':
				self.rdbuff = transaction.data
			elif reg == 'DPIDR':
				self.dpidr = transaction.data
			elif reg == 'DLCR':
				self.dlcr = transaction.data
			elif reg == 'TARGETID':
				self.targetid = transaction.data
			elif reg == 'DLPIDR':
				self.dlpidr = transaction.data
			elif reg == 'EVENTSTAT':
				self.eventstat = transaction.data
			else:
				raise ValueError(f'Invalid DP register {reg} given')
		else:
			# If the DP for this transaction is not yet known, see if this is an AP IDR transaction
			# and if so, make a new DP instance based on the decoded value
			ap = self.ap.get(self.select.currentAP)
			if ap is None:
				if transaction.register != 'IDR':
					return
				ap = self.ap[self.select.currentAP] = ADIv5AP.fromID(transaction.data)

class Decoder(srd.Decoder):
	api_version = 3
	id = 'adiv5'
	name = 'ADIv5'
	longname = 'ARM Debug Interface v5'
	desc = 'ARM ADIv5 debug protocol.'
	license = 'gplv2+'
	inputs = ['adiv5']
	outputs: list[str] = []
	tags = ['Debug/trace']
	annotations = (
		('transaction-even', 'Transaction (even)'),
		('transaction-odd', 'Transaction (odd)'),
	)
	annotation_rows = (
		('transaction-even', 'Transaction (even)', (A.TRANS_EVEN,)),
		('transaction-odd', 'Transaction (odd)', (A.TRANS_ODD,)),
	)

	def __init__(self):
		self.dp = dict[int, ADIv5DP]()

	def reset(self):
		self.transactCount = 0
		self.dp.clear()

	def start(self):
		self.reset()
		self.outputAnnotation = self.register(srd.OUTPUT_ANN)

	def annotate(self, begin: int, end: int, data: list[int | list[str]]):
		self.put(begin, end, self.outputAnnotation, data)

	def decode(self, beginSample: int, endSample: int, data: tuple[ADIv5Op, int, int, str, ADIv5AckLiteral, int]):
		'''Take a transaction from the ADIv5 de-encapsulation decoder and turn it into part of a logical transaction'''
		# Unpack the transaction
		transaction = ADIv5Transaction(*data)

		# Figure out which transaction line to display it and convert the transaction into an annotation
		line = A.TRANS_EVEN if (self.transactCount & 1) == 0 else A.TRANS_ODD
		self.transactCount += 1
		targetName = f'DP{transaction.dp}'
		if transaction.target == ADIv5Target.ap:
			targetName += ' AP'
		self.annotate(beginSample, endSample,
			[line, [f'{targetName} {transaction.rnw.name} {transaction.register[0]}: {transaction.data:08x}']])

		# If the transation failed for some reason, handle that and return
		if transaction.ack != ADIv5Ack.ok:
			return

		# If the DP for this transaction is not yet known, make a new DP instance
		dp = self.dp.get(transaction.dp)
		if dp is None:
			dp = self.dp[transaction.dp] = ADIv5DP()
		dp.decodeTransaction(transaction)
