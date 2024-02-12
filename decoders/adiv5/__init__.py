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

'''
This PD decodes the de-encapsulated ARM ADIv5 logical protocol as defined
and described in the "ARM Debug Interface v5.2" architecture specification.

This supports Debug Port versions 0, 1 and 2, covering all version of the
protocol currently published with the exception of ADIv6.

Details can be found in IHI0031 and this has been written using version g
of the specification from:
https://developer.arm.com/documentation/ihi0031/latest/
'''

from .pd import Decoder
