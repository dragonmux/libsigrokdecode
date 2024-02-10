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

from enum import Enum, unique, auto
from .pd import JTAGDevice, A

@unique
class ADIv5State(Enum):
	idle = auto()
	abort = auto()
	dpAccess = auto()
	apAccess = auto()
	inError = auto()

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

	def decodeInsn(self):
		# 8-bit instructions only extend the 4-bit ones with the high bits set for all valid ones
		# so truncate them back down to 4-bit for this having verified they're in range
		if self.device.irLength == 8 and self.device.currentInsn & 0xf0 != 0xf0:
			insn = 0
		else:
			insn = self.device.currentInsn & 0xf
		# Now look the instruction up, convert it to a decoder state and annotate the bits
		name, self.state = ADIv5Decoder.instructions.get(insn, ('UNKNOWN', ADIv5State.inError))
		self.device.decoder.annotateBits(self.device.irBegin, self.device.irEnd,
			[A.JTAG_COMMAND, [f'TAP {self.device.deviceIndex}: {name}', name]])
