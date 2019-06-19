"""
Core USB packet sniffer packet backend for OpenVizsla.
"""

import crcmod

from .protocol import OVPacketHandler

def hd(x):
    return " ".join("%02x" % i for i in x)

#  Physical layer error
HF0_ERR =  0x01
# RX Path Overflow
HF0_OVF =  0x02
# Clipped by Filter
HF0_CLIP = 0x04
# Clipped due to packet length (> 800 bytes)
HF0_TRUNC = 0x08
# First packet of capture session; IE, when the cap hardware was enabled
HF0_FIRST = 0x10
# Last packet of capture session; IE, when the cap hardware was disabled
HF0_LAST = 0x20


class USBInterpreter:

    import crcmod
    data_crc = staticmethod(crcmod.mkCrcFun(0x18005))

    def __init__(self, highspeed):
        self.frameno = None
        self.subframe = 0
        self.highspeed = True

        self.last_ts_frame = 0

        self.last_ts_print = 0
        self.last_ts_pkt = 0
        self.ts_base = 0
        self.ts_roll_cyc = 2**24

    def handlePacket(self, ts, buf, flags):
        CRC_BAD = 1
        CRC_GOOD = 2
        CRC_NONE = 3
        crc_check = CRC_NONE
        
        ts_delta_pkt = ts - self.last_ts_pkt
        self.last_ts_pkt = ts

        if ts_delta_pkt < 0:
            self.ts_base += self.ts_roll_cyc

        ts += self.ts_base


        suppress = False

        #msg = "(%s)" % " ".join("%02x" % i for i in buf)
        msg = ""

        if len(buf) != 0:
            pid = buf[0] & 0xF
            if (buf[0] >> 4) ^ 0xF != pid:
                msg += "Err - bad PID of %02x" % pid
            elif pid == 0x5:
                if len(buf) < 3:
                    msg += "RUNT frame"
                else:
                    frameno = buf[1] | (buf[2] << 8) & 0x7
                    if self.frameno == None:
                        self.subframe = None
                    else:
                        if self.subframe == None:
                            if frameno == (self.frameno + 1) & 0xFF:
                                self.subframe = 0 if self.highspeed else None
                        else:
                            self.subframe += 1
                            if self.subframe == 8:
                                if frameno == (self.frameno + 1)&0xFF:
                                    self.subframe = 0
                                else:
                                    msg += "WTF Subframe %d" % self.frameno
                                    self.subframe = None
                            elif self.frameno != frameno:
                                msg += "WTF frameno %d" % self.frameno
                                self.subframe = None
                    
                    self.frameno = frameno
                                
                    self.last_ts_frame = ts
                    suppress = True
                    msg += "Frame %d.%c" % (frameno, '?' if self.subframe == None else "%d" % self.subframe)
            elif pid in [0x3, 0xB, 0x7]:
                n = {3:0, 0xB:1, 0x7:2}[pid]

                msg += "DATA%d: %s" % (n,hd(buf[1:]))

                if len(buf) > 2:
                    calc_check = self.data_crc(buf[1:-2])^0xFFFF 
                    pkt_check = buf[-2] | buf[-1] << 8

                    if calc_check != pkt_check:
                        msg += "\tUnexpected ERR CRC"

            elif pid == 0xF:
                msg += "MDATA: %s" % hd(buf[1:])
            elif pid in [0x01, 0x09, 0x0D, 0x04]:
                if pid == 1:
                    name = "OUT"
                elif pid == 9:
                    name = "IN"
                elif pid == 0xD:
                    name = "SETUP"
                elif pid == 0x04:
                    name = "PING"
                if len(buf) < 3:
                    msg += "RUNT: %s %s" % (name, " ".join("%02x" % i for i in buf))
                else:

                    addr = buf[1] & 0x7F
                    endp = (buf[2] & 0x7) << 1 | buf[1] >> 7

                    msg += "%-5s: %d.%d" % (name, addr, endp)
            elif pid == 2:
                msg += "ACK"
            elif pid == 0xA:
                msg += "NAK"
            elif pid == 0xE:
                msg += "STALL"
            elif pid == 0x6:
                msg += "NYET"
            elif pid == 0xC:
                msg += "PRE-ERR"
                pass
            elif pid == 0x8:
                msg += "SPLIT"
                pass
            else:
                msg += "WUT"

        if not suppress:
            crc_char_d = {
                CRC_BAD: '!',
                CRC_GOOD: 'C',
                CRC_NONE: ' '
            }

            flag_field = "[  %s%s%s%s%s%s]" % (
                'L' if flags & 0x20 else ' ',
                'F' if flags & 0x10 else ' ',
                'T' if flags & 0x08 else ' ',
                'C' if flags & 0x04 else ' ',
                'O' if flags & 0x02 else ' ',
                'E' if flags & 0x01 else ' ')
            delta_subframe = ts - self.last_ts_frame
            delta_print = ts - self.last_ts_print
            self.last_ts_print = ts
            RATE=60.0e6

            subf_print = ''
            frame_print = ''

            if self.frameno != None:
                frame_print = "%3d" % self.frameno

            if self.subframe != None:
                subf_print = ".%d" % self.subframe

            print ("%s %10.6f d=%10.6f [%3s%2s +%7.3f] [%3d] %s " % (
                    flag_field, ts/RATE, (delta_print)/RATE,
                    frame_print, subf_print, delta_subframe/RATE * 1E6,
                    len(buf), msg))


def decode_flags(flags):
    ret = ""
    ret += "Error " if flags & HF0_ERR else ""
    ret += "Overflow" if flags & HF0_OVF else ""
    ret += "Clipped " if flags & HF0_CLIP else ""
    ret += "Truncated " if flags & HF0_TRUNC else ""
    ret += "First " if flags & HF0_FIRST else ""
    ret += "Last " if flags & HF0_LAST else ""
    return ret.rstrip()


class USBSniffer(OVPacketHandler):

    HANDLED_PACKET_NUMBERS = [0xac, 0xad, 0xa0]

    data_crc = staticmethod(crcmod.mkCrcFun(0x18005))

    def bytes_necessary_to_determine_size(self, packet_number):
        if packet_number == 0xa0:
            return 5
        return 1

    def __init__(self, write_handler):

        self.last_rxcmd = 0
        self.usbbuf = []
        self.highspeed = False
        self.decoder = USBInterpreter(self.highspeed)
        self.handlers = [self.handle_usb_verbose]
        self.got_start = False

        # Call the super-constructor.
        super().__init__(write_handler)


    def _packet_size(self, buf):

        if buf[0] != 0xa0:
            return 2
        else:
            #print("SIZING: %s" % " ".join("%02x" %i for i in buf))
            return (buf[4] << 8 | buf[3]) + 8


    def handle_packet(self, buf):

        if buf[0] == 0xa0:
            flags = buf[1] | buf[2] << 8

            ts = buf[5] | buf[6] << 8 | buf[7] << 16

            if flags != 0 and flags != HF0_FIRST and flags != HF0_LAST:
                print("PERR: %04X (%s)" % (flags, decode_flags(flags)))
            
            if flags & HF0_FIRST:
                self.got_start = True

            if self.got_start:
                self.handle_usb(ts, buf[8:], flags)

            if flags & HF0_LAST:

                self.got_start = False


    def handle_usb(self, ts, buf, flags):
        for handler in self.handlers:
            handler(ts, buf, flags)


    def handle_usb_verbose(self, ts, buf, flags):
            #                ChandlePacket(ts, flags, buf, len(buf))
            self.decoder.handlePacket(ts, buf, flags)
