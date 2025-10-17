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

from enum import Enum, IntEnum, auto
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

class ADIv5Ack(IntEnum):
	ok = 1
	wait = 2
	fault = 4

	@property
	def name(self) -> Literal['OK', 'WAIT', 'FAULT']:
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

class SWDDevices:
	def __init__(self, decoder: Decoder):
		self.decoder = decoder
		self.selectedDP = 0
		self.dps = []
		self.request = 0
		self.ack = 0
		self.data = 0

	def reset(self):
		pass

	def beginTransaction(self, begin: int):
		self.startSample = begin

	def endTransaction(self, end: int, request: int, ack: int, data: int, parityOk: bool):
		begin = self.startSample
		dpIndex = self.selectedDP

		target = ADIv5Target.ap if (request & (1 << 1)) != 0 else ADIv5Target.dp
		rnw = ADIv5RnW.read if (request & (1 << 2)) != 0 else ADIv5RnW.write
		addr = ((request >> 3) & 3) << 2

		accessType = 'read' if rnw == ADIv5RnW.read else 'write'
		self.decoder.annotateBits(begin, end, [A.SWD_COMMAND, [f'DP{dpIndex} {target.name} {accessType}']])
