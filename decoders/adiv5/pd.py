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
from enum import Enum, unique, auto
from typing import Literal

__all__ = ['Decoder']

class Annotations:
	'''Annotation and binary output classes.'''
	(
		TRANS_EVEN, TRANS_ODD,
	) = range(2)
A = Annotations

ADIv5Op = Literal['DP_READ', 'DP_WRITE', 'AP_READ', 'AP_WRITE']
ADIv5Ack = Literal['OK', 'WAIT', 'FAULT', 'NO-RESPONSE']

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

class ADIv5Transaction:
	def __init__(self, op: ADIv5Op, dp: int, addr: int, reg: str, ack: ADIv5Ack, data: int):
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

class ADIv5AP:
	'''This serves as a base type for all AP variants'''
	@staticmethod
	def fromID(id: int):
		'''Construct a suitable AP instance from an ID register value'''
		pass

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
				return

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
		self.dp: dict[int, ADIv5DP] = {}

	def reset(self):
		self.transactCount = 0
		self.dp.clear()

	def start(self):
		self.reset()
		self.outputAnnotation = self.register(srd.OUTPUT_ANN)

	def annotate(self, begin: int, end: int, data: list[int | list[str]]):
		self.put(begin, end, self.outputAnnotation, data)

	def decode(self, beginSample: int, endSample: int, transact: tuple[ADIv5Op, int, int, str, ADIv5Ack, int]):
		'''Take a transaction from the ADIv5 de-encapsulation decoder and turn it into part of a logical transaction'''
		# Unpack the transaction
		op, dp, addr, reg, ack, data = transact
		target, op = op.split('_')

		# Figure out which transaction line to display it and convert the transaction into an annotation
		line = A.TRANS_EVEN if (self.transactCount & 1) == 0 else A.TRANS_ODD
		self.transactCount += 1
		targetName = f'DP{dp}'
		if target == 'AP':
			targetName += ' AP'
		self.annotate(beginSample, endSample, [line, [f'{targetName} {op.lower()} {reg}: {data:08x}']])
