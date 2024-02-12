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
from typing import Literal

__all__ = ['Decoder']

ADIv5Op = Literal['DP_READ', 'DP_WRITE', 'AP_READ', 'AP_WRITE']
ADIv5Ack = Literal['OK', 'WAIT', 'FAULT', 'NO-RESPONSE']

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
	)
	annotation_rows = (
	)

	def __init__(self):
		pass

	def reset(self):
		pass

	def start(self):
		self.reset()

	def decode(self, beginSample: int, endSample: int, data: tuple[ADIv5Op, int, int, str, ADIv5Ack, int]):
		pass
