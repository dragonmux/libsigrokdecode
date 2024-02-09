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

class Decoder(srd.Decoder):
	api_version = 3
	id = 'jtag_arm'
	name = 'JTAG / ADIv5'
	longname = 'Joint Test Action Group / ARM ADIv5'
	desc = 'ARM ADIv5 JTAG debug protocol.'
	license = 'gplv2+'
	inputs = ['jtag']
	outputs = ['adiv5']
