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

from enum import IntEnum

class JEP106(IntEnum):
	'''JEP-106 manufacturer codes as seen in ARM ROM tables, JTAG ID codes, and ARM ID codes.

	These codes are taken from JEP-106 revision BM (June 2025) from the JEDEC website.
	To build an entry, first count how many continuation codes there need to be for the code's bank.
	This is the 3rd nibble. Having done this, take the manufacturer's code from the bank table,
	drop the most significant (parity) bit and make it 0, and note the resulting hex value as the lower
	two nibbles. See the diagram below for how this looks bitwise:

	* ╷11    8╷7╷6           0╷
	* │ │ │ │ │0│ │ │ │ │ │ │ │
	* ╰───┬───╯│╰──────┬──────╯
	*   Cont.  │ Manufacturer
	*   code   │     code
	*          ╰ Parity bit (0)

	Some entries are for errata seen in the wild where a manufacturer has used another's JEP-106
	mistakenly or due to bad tape-out, such entires are prefixed with ERRATA_.
	'''

	# Bank 1
	FREESCALE = 0x00e
	NXP = 0x15
	TEXAS_INSTRUMENTS = 0x015
	ATMEL = 0x01f
	ST_MICRO = 0x020
	CYPRESS = 0x034
	INFINEON = 0x041
	XILINX = 0x049

	# Bank 3
	NORDIC = 0x244

	# Bank 4
	ERRATA_XILINX = 0x309

	# Bank 5
	RENESAS = 0x423
	ARM = 0x43b

	# Bank 6
	SPECULAR_NETWORKS = 0x501

	# Bank 7
	ENERGY_MICRO = 0x673

	# Bank 8
	GIGADEVICE = 0x751

	# Bank 10
	RASPBERRY_PI = 0x913

	# Bank 11
	ARM_CHINA = 0xa75

	def __str__(self) -> str:
		match self:
			case JEP106.FREESCALE:
				return 'Freescale'
			case JEP106.NXP:
				return 'NXP'
			case JEP106.TEXAS_INSTRUMENTS:
				return 'Texas Instruments'
			case JEP106.ATMEL:
				return 'Atmel'
			case JEP106.ST_MICRO:
				return 'ST Microelectronics'
			case JEP106.CYPRESS:
				return 'Cypress Semiconductor'
			case JEP106.INFINEON:
				return 'Infineon'
			case JEP106.XILINX:
				return 'Xilinx'
			case JEP106.NORDIC:
				return 'Nordic Semiconductor'
			case JEP106.ERRATA_XILINX:
				return 'Xilinx (Errata)'
			case JEP106.RENESAS:
				return 'Renesas'
			case JEP106.ARM:
				return 'ARM'
			case JEP106.SPECULAR_NETWORKS:
				return 'Specular Networks'
			case JEP106.ENERGY_MICRO:
				return 'Energy Micro'
			case JEP106.GIGADEVICE:
				return 'GigaDevice'
			case JEP106.RASPBERRY_PI:
				return 'Raspberry Pi Foundation'
			case JEP106.ARM_CHINA:
				return 'ARM China'
