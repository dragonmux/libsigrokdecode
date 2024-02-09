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

__all__ = ['Decoder']

class Annotations:
	'''Annotation and binary output classes.'''
	(
		JTAG_ITEM, JTAG_FIELD, JTAG_COMMAND, JTAG_NOTE,
		ADIV5_ACK_OK, ADIV5_ACK_WAIT, ADIV5_ACK_FAULT,
		ADIV5_READ, ADIV5_WRITE, ADIV5_REGISTER,
		ADIV5_REQUEST, ADIV5_RESULT,
	) = range(12)
A = Annotations

class Decoder(srd.Decoder):
	api_version = 3
	id = 'jtag_arm'
	name = 'JTAG / ADIv5'
	longname = 'Joint Test Action Group / ARM ADIv5'
	desc = 'ARM ADIv5 JTAG debug protocol.'
	license = 'gplv2+'
	inputs = ['jtag']
	outputs = ['adiv5']
	tags = ['Debug/trace']
	annotations = (
		# JTAG encapsulation annotations
		('item', 'Item'),
		('field', 'Field'),
		('command', 'Command'),
		('note', 'Note'),
		# ADIv5 acknowledgement annotations
		('adiv5-ack-ok', 'ACK (OK)'),
		('adiv5-ack-wait', 'ACK (WAIT)'),
		('adiv5-ack-fault', 'ACK (FAULT)'),
		# ADIv5 request annotations
		('adiv5-read', 'Read'),
		('adiv5-write', 'Write'),
		('adiv5-register', 'Register'),
		# ADIv5 data annotations
		('adiv5-request', 'Request'),
		('adiv5-result', 'Result'),
	)
	annotation_rows = (
		('items', 'Items', (A.JTAG_ITEM,)),
		('fields', 'Fields', (A.JTAG_FIELD,)),
		('commands', 'Commands', (A.JTAG_COMMAND,)),
		('notes', 'Notes', (A.JTAG_NOTE,)),
		('request', 'Request', (A.ADIV5_READ, A.ADIV5_WRITE, A.ADIV5_REGISTER, A.ADIV5_REQUEST)),
		('result', 'Result', (A.ADIV5_ACK_OK, A.ADIV5_ACK_WAIT, A.ADIV5_ACK_FAULT, A.ADIV5_RESULT)),
	)
