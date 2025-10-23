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

from abc import ABCMeta, abstractmethod

from .jep106 import JEP106

class Register(metaclass = ABCMeta):
	def __init__(self):
		self.value = 0

	@abstractmethod
	def changeValue(self, value: int) -> None:
		raise NotImplementedError('Register must implement value updates')

	@abstractmethod
	def __str__(self) -> str:
		raise NotImplementedError('Register must implement string conversion')

class ADIv5DPAbort(Register):
	def changeValue(self, abort: int) -> None:
		self.value = abort

	@property
	def overrunErrorClear(self):
		return (self.value & (1 << 4)) != 0

	@property
	def writeDataErrorClear(self):
		return (self.value & (1 << 3)) != 0

	@property
	def stickyErrorClear(self):
		return (self.value & (1 << 2)) != 0

	@property
	def stickyCompareClear(self):
		return (self.value & (1 << 1)) != 0

	@property
	def apTransactionAbort(self):
		return (self.value & (1 << 0)) != 0

	def __str__(self) -> str:
		bits = list[str]()
		if self.overrunErrorClear:
			bits.append('Overrun Error')
		if self.writeDataErrorClear:
			bits.append('Write Data Error')
		if self.stickyErrorClear:
			bits.append('Sticky Error')
		if self.stickyCompareClear:
			bits.append('Sticky Compare')
		if self.apTransactionAbort:
			bits.append('AP Transaction')
		return f'Abort: {" | ".join(bits)}'

class ADIv5DPCtrlStat(Register):
	def changeValue(self, ctrlStatus: int) -> None:
		self.value = ctrlStatus

	def __str__(self) -> str:
		return f'{self.value:#08x}'

class ADIv5DPID(Register):
	def changeValue(self, dpidr: int):
		self.value = dpidr

	@property
	def isMinDP(self):
		return (self.value & (1 << 16)) != 0

	def __str__(self):
		vendor = JEP106((self.value & 0xf00) | ((self.value & 0xfe) >> 1))
		version = (self.value >> 12) & 0xf
		revision = (self.value >> 28) & 0xf
		minDP = ' Min-DP' if self.isMinDP else ''
		return f'{vendor} DPv{version} rev{revision}{minDP}'

class ADIv5DPTargetID(Register):
	def changeValue(self, targetID: int):
		self.value = targetID

	def __str__(self):
		vendor = JEP106((self.value & 0xf00) | ((self.value & 0xfe) >> 1))
		partNumber = (self.value >> 12) & 0xffff
		return f'{vendor} MPN {partNumber:#03x}'

class ADIv5DPTargetSelect(Register):
	def changeValue(self, targetSelect: int) -> None:
		self.value = targetSelect

	def __str__(self) -> str:
		vendor = JEP106((self.value & 0xf00) | ((self.value & 0xfe) >> 1))
		partNumber = (self.value >> 12) & 0xffff
		dp = (self.value >> 28) & 0xf
		return f'{vendor} MPN {partNumber:#03x} DP{dp}'

class ADIv5DPSelect(Register):
	'''Internal representation of the state of the DP SELECT register'''
	def __init__(self):
		super().__init__()
		self.currentAP = 0
		self.apBank = 0
		self.dpBank = 0

	def changeValue(self, select: int):
		'''Decode a write to the SELECT register to get the new value'''
		self.currentAP = (select >> 24) & 0xff
		self.apBank = (select >> 4) & 0xf
		self.dpBank = select & 0xf
		self.value = select

	def __str__(self) -> str:
		return f'Select DP bank {self.dpBank}, AP{self.currentAP} bank {self.apBank}'
