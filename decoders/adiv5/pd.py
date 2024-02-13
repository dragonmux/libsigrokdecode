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

class Annotations:
	'''Annotation and binary output classes.'''
	(
		TRANS_EVEN, TRANS_ODD,
	) = range(2)
A = Annotations

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
		('transaction-even', 'Transaction (even)'),
		('transaction-odd', 'Transaction (odd)'),
	)
	annotation_rows = (
		('transaction-even', 'Transaction (even)', (A.TRANS_EVEN,)),
		('transaction-odd', 'Transaction (odd)', (A.TRANS_ODD,)),
	)

	def __init__(self):
		pass

	def reset(self):
		self.transactCount = 0

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
