#!/usr/bin/env python

# === LICENSE STATEMENT ===
# Copyright (c) 2011 Sebastian J. Bronner <waschtl@sbronner.com>
#
# Copying and distribution of this file, with or without modification, are
# permitted in any medium without royalty provided the copyright notice and
# this notice are preserved.
# === END LICENSE STATEMENT ===
# modified: HappyCodingRobot
#   - added frames, different font styles and command-line parsing with argparse-lib ..
#
# On systems with access to sysfs under /sys, this script will use the three
# variables DEV_CLASS, DEV_VENDOR, and DEV_PRODUCT to find the device file
# under /dev automatically. This behavior can be overridden by setting the
# variable DEV_NODE to the device file path. This is intended for cases, where
# either sysfs is unavailable or unusable by this script for some reason.
# Please beware that DEV_NODE must be set to None when not used, else you will
# be bitten by the NameError exception.

from __future__ import print_function
from __future__ import division

import array
import fcntl
import os
import re
import struct
import subprocess
import sys
import termios
import textwrap
import argparse
import math
import contextlib

try:
    from configparser import SafeConfigParser
except ImportError:  # Python 2
    from ConfigParser import SafeConfigParser

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from PIL import ImageOps

try:
    from pyqrcode import QRCode
    USE_QR = True
except ImportError as error:
    e_qrcode = error
    USE_QR = False
try:
    import barcode
    USE_BARCODE = True
except ImportError as error:
    e_barcode = error
    USE_BARCODE = False


DESCRIPTION = 'Linux Software to print with LabelManager PnP from Dymo\n written in Python'
DEV_CLASS       = 3
DEV_VENDOR      = 0x0922
DEV_PRODUCT     = 0x1002
#DEV_PRODUCT     = 0x1001
DEV_NODE        = None
DEV_NAME        = 'Dymo LabelManager PnP'
#FONT_FILENAME  = '/usr/share/fonts/truetype/ttf-bitstream-vera/Vera.ttf'
FONT_CONFIG = {'regular':'/usr/share/fonts/truetype/ubuntu-font-family/Ubuntu-R.ttf',     # regular font
               'bold':'/usr/share/fonts/truetype/ubuntu-font-family/Ubuntu-B.ttf',        # bold font
               'italic':'/usr/share/fonts/truetype/ubuntu-font-family/Ubuntu-RI.ttf',       # italic font
               'narrow':'/usr/share/fonts/truetype/ubuntu-font-family/Ubuntu-C.ttf'    # narrow/condensed
               }
FONT_SIZERATIO  = 7./8
#CONFIG_FILE     = '.dymoprint'
CONFIG_FILE     = 'dymoprint.ini'
VERSION         = "0.3.4 (2016-03-14)"


class DymoPrintException(Exception):
    """Exception raised for errors in dymoprint driver printing

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class DymoLabeler:
    """Create and work with a Dymo LabelManager PnP object.

    This class contains both mid-level and high-level functions. In general,
    the high-level functions should be used. However, special purpose usage
    may require the mid-level functions. That is why they are provided.
    However, they should be well understood before use. Look at the
    high-level functions for help. Each function is marked in its docstring
    with 'HLF' or 'MLF' in parentheses.
    """

    _ESC = 0x1b
    _SYN = 0x16
    _MAX_BYTES_PER_LINE = 8  # 64 pixels on a 12mm tape

    def __init__(self, dev):
        """Initialize the LabelManager object. (HLF)"""

        self.cmd = []
        self.response = False
        self.bytesPerLine_ = None
        self.dotTab_ = 0
        self.dev = open(dev, 'rb+')
        self.maxLines = 200

    def sendCommand(self):
        """Send the already built command to the LabelManager. (MLF)"""

        if len(self.cmd) == 0:
            return
        cmdBin = array.array('B', self.cmd)
        cmdBin.tofile(self.dev)
        self.cmd = []
        if not self.response:
            return
        self.response = False
        responseBin = self.dev.read(8)
        response = array.array('B', responseBin).tolist()
        return response

    def resetCommand(self):
        """Remove a partially built command. (MLF)"""

        self.cmd = []
        self.response = False

    def buildCommand(self, cmd):
        """Add the next instruction to the command. (MLF)"""

        self.cmd += cmd

    def statusRequest(self):
        """Set instruction to get the device's status. (MLF)"""

        cmd = [self._ESC, ord('A')]
        self.buildCommand(cmd)
        self.response = True

    def dotTab(self, value):
        """Set the bias text height, in bytes. (MLF)"""

        if value < 0 or value > self._MAX_BYTES_PER_LINE:
            raise ValueError
        cmd = [self._ESC, ord('B'), value]
        self.buildCommand(cmd)
        self.dotTab_ = value
        self.bytesPerLine_ = None

    def tapeColor(self, value):
        """Set the tape color. (MLF)"""

        if value < 0: raise ValueError
        cmd = [self._ESC, ord('C'), value]
        self.buildCommand(cmd)

    def bytesPerLine(self, value):
        """Set the number of bytes sent in the following lines. (MLF)"""

        if value < 0 or value + self.dotTab_ > self._MAX_BYTES_PER_LINE:
            raise ValueError
        if value == self.bytesPerLine_:
            return
        cmd = [self._ESC, ord('D'), value]
        self.buildCommand(cmd)
        self.bytesPerLine_ = value

    def cut(self):
        """Set instruction to trigger cutting of the tape. (MLF)"""

        cmd = [self._ESC, ord('E')]
        self.buildCommand(cmd)

    def line(self, value):
        """Set next printed line. (MLF)"""

        self.bytesPerLine(len(value))
        cmd = [self._SYN] + value
        self.buildCommand(cmd)

    def chainMark(self):
        """Set Chain Mark. (MLF)"""

        self.dotTab(0)
        self.bytesPerLine(self._MAX_BYTES_PER_LINE)
        self.line([0x99] * self._MAX_BYTES_PER_LINE)

    def skipLines(self, value):
        """Set number of lines of white to print. (MLF)"""

        if value <= 0:
            raise ValueError
        self.bytesPerLine(0)
        cmd = [self._SYN] * value
        self.buildCommand(cmd)

    def initLabel(self):
        """Set the label initialization sequence. (MLF)"""

        cmd = [0x00] * 8
        self.buildCommand(cmd)

    def getStatus(self):
        """Ask for and return the device's status. (HLF)"""

        self.statusRequest()
        response = self.sendCommand()
        print(response)

    def printLabel(self, lines, margin=56*2):
        """Print the label described by lines. (Automatically split label if 
           larger than maxLines)"""

        while len(lines) > self.maxLines + 1:
            self.rawPrintLabel(lines[0:self.maxLines], margin=0)
            del lines[0:self.maxLines]
        self.rawPrintLabel(lines, margin=margin)

    def rawPrintLabel(self, lines, margin=56*2):
        """Print the label described by lines. (HLF)"""

        # optimize the matrix for the dymo label printer
        dottab = 0
        while [] not in lines and max(line[0] for line in lines) == 0:
            lines = [line[1:] for line in lines]
            dottab += 1
        for line in lines:
            while len(line) > 0 and line[-1] == 0:
                del line[-1]

        self.initLabel
        self.tapeColor(0)
        self.dotTab(dottab)
        for line in lines:
            self.line(line)
        if margin > 0:
            self.skipLines(margin)
        self.statusRequest()
        response = self.sendCommand()
        print(response)


if USE_BARCODE:
    def mm2px(mm, dpi=25.4):
        return (mm * dpi) / 25.4

    class ImageWriter(barcode.writer.BaseWriter):

        def __init__(self):
            barcode.writer.BaseWriter.__init__(self, self._init,
                    self._paint_module, None, self._finish)
            self.format = 'PNG'
            self.dpi = 25.4
            self._image = None
            self._draw = None
            self.vertical_margin = 0

        def calculate_size(self, modules_per_line, number_of_lines, dpi=25.4):
            width = 2 * self.quiet_zone + modules_per_line * self.module_width
            height = self.vertical_margin * 2 + self.module_height * number_of_lines
            return int(mm2px(width, dpi)), int(mm2px(height, dpi))

        def render(self, code):
            """Renders the barcode to whatever the inheriting writer provides,
            using the registered callbacks.

            :parameters:
                code : List
                    List of strings matching the writer spec
                    (only contain 0 or 1).
            """
            if self._callbacks['initialize'] is not None:
                self._callbacks['initialize'](code)
            ypos = self.vertical_margin
            for cc, line in enumerate(code):
                """
                Pack line to list give better gfx result, otherwise in can
                result in aliasing gaps
                '11010111' -> [2, -1, 1, -1, 3]
                """
                line += ' '
                c = 1
                mlist = []
                for i in range(0, len(line) - 1):
                    if line[i] == line[i+1]:
                        c += 1
                    else:
                        if line[i] == "1":
                            mlist.append(c)
                        else:
                            mlist.append(-c)
                        c = 1
                # Left quiet zone is x startposition
                xpos = self.quiet_zone
                bxs = xpos  # x start of barcode
                for mod in mlist:
                    if mod < 1:
                        color = self.background
                    else:
                        color = self.foreground
                    # remove painting for background colored tiles?
                    self._callbacks['paint_module'](
                        xpos, ypos, self.module_width * abs(mod), color
                    )
                    xpos += self.module_width * abs(mod)
                bxe = xpos
                # Add right quiet zone to every line, except last line,
                # quiet zone already provided with background,
                # should it be removed complety?
                if (cc + 1) != len(code):
                    self._callbacks['paint_module'](
                        xpos, ypos, self.quiet_zone, self.background
                    )
                ypos += self.module_height
            return self._callbacks['finish']()

        def _init(self, code):
            size = self.calculate_size(len(code[0]), len(code), self.dpi)
            self._image = Image.new('1', size, self.background)
            self._draw = ImageDraw.Draw(self._image)

        def _paint_module(self, xpos, ypos, width, color):
            size = [(mm2px(xpos, self.dpi), mm2px(ypos, self.dpi)),
                    (mm2px(xpos + width, self.dpi),
                        mm2px(ypos + self.module_height, self.dpi))]
            self._draw.rectangle(size, outline=color, fill=color)

        def _finish(self):
            return self._image

        def save(self, filename, output):
            filename = '{0}.{1}'.format(filename, self.format.lower())
            output.save(filename, self.format.upper())
            return filename


def raiseException(message=None):
    if message:
        print(message, file=sys.stderr)
    raise DymoPrintException(message)


def pprint(par, fd=sys.stdout):
    rows, columns = struct.unpack('HH', fcntl.ioctl(sys.stderr,
        termios.TIOCGWINSZ, struct.pack('HH', 0, 0)))
    print(textwrap.fill(par, columns), file=fd)


def getDeviceFile(classID, vendorID, productID):
    # find file containing the device's major and minor numbers
    searchdir = '/sys/bus/hid/devices'
    pattern = '^%04d:%04X:%04X.[0-9A-F]{4}$' % (classID, vendorID, productID)
    deviceCandidates = os.listdir(searchdir)
    foundpath = None
    for devname in deviceCandidates:
        if re.match(pattern, devname):
            foundpath = os.path.join(searchdir, devname)
            break
    if not foundpath:
        return
    searchdir = os.path.join(foundpath, 'hidraw')
    devname = os.listdir(searchdir)[0]
    foundpath = os.path.join(searchdir, devname)
    filepath = os.path.join(foundpath, 'dev')

    # get the major and minor numbers
    f = open(filepath, 'r')
    devnums = [int(n) for n in f.readline().strip().split(':')]
    f.close()
    devnum = os.makedev(devnums[0], devnums[1])

    # check if a symlink with the major and minor numbers is available
    filepath = '/dev/char/%d:%d' % (devnums[0], devnums[1])
    if os.path.exists(filepath):
        return os.path.realpath(filepath)

    # check if the relevant sysfs path component matches a file name in
    # /dev, that has the proper major and minor numbers
    filepath = os.path.join('/dev', devname)
    if os.stat(filepath).st_rdev == devnum:
        return filepath

    # search for a device file with the proper major and minor numbers
    for dirpath, dirnames, filenames in os.walk('/dev'):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.stat(filepath).st_rdev == devnum:
                return filepath


def access_error(dev):
    pprint('You do not have sufficient access to the device file %s:' % dev,
        sys.stderr)
    subprocess.call(['ls', '-l', dev], stdout=sys.stderr)
    print(file=sys.stderr)
    filename = "91-dymo-labelmanager-pnp.rules"
    pprint('You probably want to add a rule like one of the following in /etc/udev/rules.d/' + filename, sys.stderr)
    with open(filename, 'r') as fin:
      print(fin.read(), file=sys.stderr)
    pprint('Following that, restart udev and re-plug your device. See README.md for details', sys.stderr)


''' reading config file, input: 'filename' '''
def read_config(conf_file):
    global FONT_CONFIG
    conf = SafeConfigParser(FONT_CONFIG)
    if not conf.read(conf_file):
        print('# Config file "%s" not found: writing new config file.\n' % conf_file)
        write_config(conf_file)
    else:
        # reading FONTS section
        if not 'FONTS' in conf.sections():
            raiseException('! config file "%s" not valid. Please change or remove.' %conf_file)
        for key in FONT_CONFIG.keys():
            FONT_CONFIG[key] = conf.get('FONTS',key)
        # more sections later ..


''' writing config file, input: 'filename' '''
def write_config(conf_file):
    config=SafeConfigParser()
    # adding sections and keys
    config.add_section('FONTS')
    for key in FONT_CONFIG.keys():
        config.set('FONTS', key, FONT_CONFIG[key])
    # writing config file
    with open(conf_file, 'w') as configfile:
        config.write(configfile)


''' scaling pixel up, input: (x,y),scale-factor '''
def scaling(pix, sc):
    return [(pix[0]+i, pix[1]+j) for i in range(sc) for j in range(sc)]


''' decoding text parameter depending on system encoding '''
def to_unicode(argument_string):
    try:
        unicode  # this passes on Python 2, where we need to decode, but not on Python 3
        return argument_string.decode(sys.getfilesystemencoding())
    except NameError:
        return argument_string

@contextlib.contextmanager
def draw_image(bitmap):
    drawobj = ImageDraw.Draw(bitmap)
    try:
        yield drawobj
    finally:
        del drawobj

def parse_args(args=None):
    # check for any text specified on the command line
    parser = argparse.ArgumentParser(description=DESCRIPTION+' \n Version: '+VERSION)
    parser.add_argument('text',nargs='+',help='Text Parameter, each parameter gives a new line',type=to_unicode)
    parser.add_argument('-f',action="count",help='Draw frame around the text, more arguments for thicker frame')
    parser.add_argument('-s',choices=['r','b','i','n'],default='r',help='Set fonts style (regular,bold,italic,narrow)')
    parser.add_argument('-u',nargs='?',help='Set user font, overrides "-s" parameter')
    parser.add_argument('-v',action='store_true',help='Preview label, do not print')
    parser.add_argument('-qr',action='store_true',help='Printing the first text parameter as QR-code')
    parser.add_argument('-c', choices=['code39','code128','ean','ean13','ean8','gs1','gtin','isbn','isbn10','isbn13','issn','jan','pzn','upc','upca'],
                        default=False, help='Printing the first text parameter as barcode')
    parser.add_argument('-p', '--picture', help="Print the specified picture")
    parser.add_argument('-m',type=int,help='Override margin (default is 56*2)')
    #parser.add_argument('-t',type=int,choices=[6, 9, 12],default=12,help='Tape size: 6,9,12 mm, default=12mm')
    parser.add_argument('-pdb',action='store_true',help='Run pdb if an exception occurs')
    if args == None:
        return parser.parse_args()
    else:
        return parser.parse_args(args)

def main(args):
    # read config file
    conf_path = os.path.dirname(os.path.realpath(__file__))
    read_config(os.path.join(conf_path, CONFIG_FILE))

    labeltext = args.text
    # select font style and offset from parameter
    if args.s == 'r':
        FONT_FILENAME = FONT_CONFIG['regular']
    elif args.s == 'b':
        FONT_FILENAME = FONT_CONFIG['bold']
    elif args.s == 'i':
        FONT_FILENAME = FONT_CONFIG['italic']
    elif args.s == 'n':
        FONT_FILENAME = FONT_CONFIG['narrow']
    else:
        FONT_FILENAME = FONT_CONFIG['regular']

    if args.u is not None:
        if os.path.isfile(args.u):
            FONT_FILENAME = args.u
        else:
            raiseException("Error: file '%s' not found." % args.u)

    # check if barcode, qrcode or text should be printed, use frames only on text
    if args.qr and not USE_QR:
        raiseException("Error: %s" % e_qrcode)

    if args.c and not USE_BARCODE:
        raiseException("Error: %s" % e_barcode)

    if args.c and args.qr:
        raiseException("Error: can not print both QR and Barcode on the same label (yet)")

    bitmaps = []

    if args.qr:
        # create QR object from first string
        code = QRCode(labeltext.pop(0), error='M')
        qr_text = code.text(quiet_zone=1).split()

        # create an empty label image
        labelheight = DymoLabeler._MAX_BYTES_PER_LINE * 8
        labelwidth = labelheight
        qr_scale = labelheight // len(qr_text)
        qr_offset = (labelheight - len(qr_text)*qr_scale) // 2

        if not qr_scale:
            raiseException("Error: too much information to store in the QR code, points are smaller than the device resolution")

        codebitmap = Image.new('1', (labelwidth, labelheight))

        with draw_image(codebitmap) as labeldraw:
            # write the qr-code into the empty image
            for i, line in enumerate(qr_text):
                for j in range(len(line)):
                    if line[j] == '1':
                        pix = scaling((j*qr_scale, i*qr_scale+qr_offset), qr_scale)
                        labeldraw.point(pix, 255)

        bitmaps.append(codebitmap)

    elif args.c:
        code = barcode.get(args.c, labeltext.pop(0), writer=ImageWriter())
        codebitmap = code.render({
            'font_size': 0,
            'vertical_margin': 8,
            'module_height': (DymoLabeler._MAX_BYTES_PER_LINE * 8) - 16,
            'module_width': 2,
            'background': 'black',
            'foreground': 'white',
            })

        bitmaps.append(codebitmap)

    if labeltext:
        if args.f == None:
            fontoffset = 0
        else:
            fontoffset = min(args.f, 3)

        # create an empty label image
        labelheight = DymoLabeler._MAX_BYTES_PER_LINE * 8
        lineheight = float(labelheight) / len(labeltext)
        fontsize = int(round(lineheight * FONT_SIZERATIO))
        font = ImageFont.truetype(FONT_FILENAME, fontsize)
        labelwidth = max(font.getsize(line)[0] for line in labeltext) + (fontoffset*2)
        textbitmap = Image.new('1', (labelwidth, labelheight))
        with draw_image(textbitmap) as labeldraw:

            # draw frame into empty image
            if args.f is not None:
                labeldraw.rectangle(((0,0),(labelwidth-1,labelheight-1)),fill=255)
                labeldraw.rectangle(((fontoffset,fontoffset),(labelwidth-(fontoffset+1),labelheight-(fontoffset+1))),fill=0)

            # write the text into the empty image
            for i, line in enumerate(labeltext):
                lineposition = int(round(i * lineheight))
                labeldraw.text((fontoffset, lineposition), line, font=font, fill=255)

        bitmaps.append(textbitmap)

    if args.picture:
        labelheight = DymoLabeler._MAX_BYTES_PER_LINE * 8
        with Image.open(args.picture) as img:
            if img.height > labelheight:
                ratio = labelheight / img.height
                img.thumbnail((int(math.ceil(img.width*ratio)), labelheight), Image.ANTIALIAS)
            bitmaps.append(ImageOps.invert(img).convert('1'))

    if len(bitmaps) > 1:
        padding = 4
        labelbitmap = Image.new('1', (sum(b.width for b in bitmaps) + padding*(len(bitmaps) - 1), bitmaps[0].height))
        offset = 0
        for bitmap in bitmaps:
            labelbitmap.paste(bitmap, box=(offset, 0))
            offset += bitmap.width + padding
    else:
        labelbitmap = bitmaps[0]

    # convert the image to the proper matrix for the dymo labeler object
    labelrotated = labelbitmap.transpose(Image.ROTATE_270)
    labelstream = labelrotated.tobytes()
    labelstreamrowlength = int(math.ceil(labelbitmap.height/8))
    if len(labelstream)//labelstreamrowlength != labelbitmap.width:
        raiseException('An internal problem was encountered while processing the label '
            'bitmap!')
    labelrows = [labelstream[i:i+labelstreamrowlength] for i in
        range(0, len(labelstream), labelstreamrowlength)]
    labelmatrix = [array.array('B', labelrow).tolist() for labelrow in
        labelrows]

    # print or show the label
    if args.v == True:
        print('Demo mode: showing label..')
        # fix size, adding print borders
        labelimage = Image.new('L', (56+labelbitmap.width+56, labelbitmap.height))
        labelimage.paste(labelbitmap, (56,0))
        ImageOps.invert(labelimage).show()
    else:
        # get device file name
        if not DEV_NODE:
            dev = getDeviceFile(DEV_CLASS, DEV_VENDOR, DEV_PRODUCT)
        else:
            dev = DEV_NODE

        if not dev:
            raiseException("The device '%s' could not be found on this system." % DEV_NAME)

        # create dymo labeler object
        try:
            lm = DymoLabeler(dev)
        except IOError:
            raiseException(access_error(dev))

        print('Printing label..')
        if args.m is not None:
            lm.printLabel(labelmatrix, margin=args.m)
        else:
            lm.printLabel(labelmatrix)


if __name__ == '__main__':
    args = parse_args()
    try:
        main(args)
    except:
        if not args.pdb:
            raise
        import traceback
        import pdb
        type, value, tb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(tb)


# TODO
# ? support multiple ProductIDs (1001, 1002) -> use usb-modeswitch?
# o put everything in classes that would need to be used by a GUI
# x for more options use command line parser framework
# x allow selection of font with command line options
# o allow font size specification with command line option (points, pixels?)
# x provide an option to show a preview of what the label will look like
# x read and write a .dymoprint file containing user preferences
# o print graphics and barcodes
# x plot frame around label
