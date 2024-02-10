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

from typing import TypedDict, Required

class JTAGIRQuirks(TypedDict):
	length: int
	value: int

class JTAGDeviceDescription(TypedDict, total = False):
	idcode: Required[int]
	mask: Required[int]
	mfr: Required[str]
	description: Required[str]
	irQuirks: JTAGIRQuirks

'''Descriptions, ID codes and quirks for supported devices'''
jtagDevices: tuple[JTAGDeviceDescription] = (
	{
		'idcode': 0x0ba00477,
		'mask': 0x0fffffff,
		'mfr': 'ARM',
		'description': 'ADIv5 JTAG-DPv0',
	},
	{
		'idcode': 0x0ba01477,
		'mask': 0x0fffffff,
		'mfr': 'ARM',
		'description': 'ADIv5 JTAG-DPv1',
	},
	{
		'idcode': 0x0ba02477,
		'mask': 0x0fffffff,
		'mfr': 'ARM',
		'description': 'ADIv5 JTAG-DPv2',
	},
	{
		'idcode': 0x03600093,
		'mask': 0x0fe00fff,
		'mfr': 'Xilinx',
		'description': 'FPGA',
		'irQuirks': {
			'length': 6,
			'value': 0x11
		}
	}
)
