#!/usr/bin/env python.

# This needs python3.3 or greater - argparse changes behavior
# TODO - workaround

from .. import libov, find_openvizsla_asset, OVCaptureUSBSpeed

from ..device import OVDevice
from ..firmware import OVFirmwarePackage
from ..sniffer import USBEventSink, USBSimplePrintSink


import argparse
import time

import zipfile

import sys
import os, os.path
import struct

# We check the Python version in __main__ so we don't
#   rudely bail if someone imports this module.
MIN_MAJOR = 3
MIN_MINOR = 3

default_package = os.getenv('OV_PKG')
if default_package is None:
    default_package = find_openvizsla_asset("ov3.fwpkg")

def as_ascii(arg):
    if arg == None:
        return None
    return arg.encode('ascii')

class Command:
    def __subclasshook__(self):
        pass

    @staticmethod
    def setup_args(sp):
        pass

__cmd_keeper = []
def command(_name, *_args):
    def _i(todeco):
        class _sub(Command):
            name = _name

            @staticmethod
            def setup_args(sp):
                for (name, typ, *default) in _args:
                    if len(default):
                            name = "--" + name
                            default = default[0]
                    else:
                        default = None
                    sp.add_argument(name, type=typ, default=default)

            @staticmethod
            def go(dev, args):
                aarray = dict([(i, getattr(args, i)) for (i, *_) in _args])
                todeco(dev, **aarray)
        __cmd_keeper.append(_sub)
        return todeco

    return _i

int16 = lambda x: int(x, 16)


def check_ulpi_clk(dev):
    clks_up = dev.regs.ucfg_stat

    if not clks_up:
        print("ULPI Clock has not started up - osc?")
        return 1

    return 0

@command('uwrite', ('addr', str), ('val', int16))
def uwrite(dev, addr, val):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    dev.ulpiwrite(addr, val)

@command('uread', ('addr', str))
def uread(dev, addr):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    print ("ULPI %02x: %02x" % (addr, dev.ulpiread(addr)))

@command('report')
def report(dev):

    print("USB PHY Tests")
    if check_ulpi_clk(dev):
        print("\tWARNING: ULPI PHY clock not started; skipping ULPI tests")
    else:
        # display the ULPI identifier
        ident = 0
        for x in [dev.ulpi_regs.vidh,
                dev.ulpi_regs.vidl,
                dev.ulpi_regs.pidh,
                dev.ulpi_regs.pidl]:
            ident <<= 8
            ident |= x

        name = 'unknown'
        if ident == OVDevice.USB334X_DEVICE_ID:
            name = 'SMSC 334x'
        print("\tULPI PHY ID: %08x (%s)" % (ident, name))

        # do in depth phy tests
        if ident == OVDevice.USB334X_DEVICE_ID:
            dev.ulpi_regs.scratch = 0
            dev.ulpi_regs.scratch_set = 0xCF
            dev.ulpi_regs.scratch_clr = 0x3C

            stat = "OK" if dev.ulpi_regs.scratch == 0xC3 else "FAIL"

            print("\tULPI Scratch register IO test: %s" % stat)
            print("\tPHY Function Control Reg:  %02x" % dev.ulpi_regs.func_ctl)
            print("\tPHY Interface Control Reg: %02x" % dev.ulpi_regs.intf_ctl)
        else:
            print("\tUnknown PHY - skipping phy tests")

    print ("SDRAM tests")
    def cb(n, ok):
        print("\t... %d: %s" % (n, "OK" if ok else "FAIL"))
    stat = do_sdramtests(dev, cb)
    if stat == -1:
        print("\t... all passed")


class OutputCustom(USBEventSink):
    def __init__(self, output, speed):
        self.output = output
        self.speed = speed
        self.last_ts = 0
        self.ts_offset = 0
        try:
            with open("template_custom.txt") as f:
                self.template = f.readline()
        except:
            self.template = "data=%s speed=%s time=%f\n"

    def handle_usb_packet(self, ts, pkt, flags):
        if ts < self.last_ts:
            self.ts_offset += 0x1000000
        self.last_ts = ts
        pkthex = " ".join("%02x" % x for x in pkt)
        self.output.write(bytes(self.template % (pkthex, self.speed.upper(), (ts + self.ts_offset) / 60e6), "ascii"))


class OutputITI1480A(USBEventSink):
    def __init__(self, output, speed):
        self.output = output
        self.speed = speed
        self.ts_offset = 0
        self.ts_last = None

    def handle_usb_packet(self, ts, pkt, flags):
        buf = []

        # Skip SOF and empty packets
        if (len(pkt) == 0) or (pkt[0] == 0xa5):
            return

        # Normalize timestamp and get delta vs prev packet
        if self.ts_last is None:
            self.ts_last = ts

        if ts < self.ts_last:
            self.ts_offset

        ts_delta = ts - self.ts_last

        self.ts_last = ts

        # Prepare data
        buf = bytearray(4 + 2 + 2*len(pkt) + 2)

        # Write timestamp delta
        buf[0] = (ts_delta & 0x0000ff0) >> 4
        buf[1] = (ts_delta & 0x000000f) | 0x30
        buf[2] = (ts_delta & 0xff00000) >> 20
        buf[3] = (ts_delta & 0x00ff000) >> 12

        # Write packet start
        buf[4] = 0x40
        buf[5] = 0xc0

        # Write packet data
        buf[6:-2:2] = pkt
        buf[7:-2:2] = b'\x80' * len(pkt)

        # Write packet end
        buf[-2] = 0x00
        buf[-1] = 0xc0

        # To file
        self.output.write(buf)


class OutputPcap(USBEventSink):
    LINK_TYPE = 255 #FIXME

    def __init__(self, output):
        self.output = output
        self.output.write(struct.pack("IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 1<<20, self.LINK_TYPE))

    def handle_usb_packet(self, ts, pkt, flags):
        self.output.write(struct.pack("IIIIH", 0, 0, len(pkt) + 2, len(pkt) + 2, flags))
        self.output.write(pkt)

def do_sdramtests(dev, cb=None, tests = range(0, 6)):

    for i in tests:
        dev.regs.SDRAM_TEST_CMD = 0x80 | i
        stat = 0x40
        while (stat & 0x40):
            time.sleep(0.1)
            stat = dev.regs.SDRAM_TEST_CMD 

        ok = stat & 0x20
        if cb is not None:
            cb(i, ok)

        if not ok:
            return i
    else:
        return -1

@command('sdramtest')
def sdramtest(dev):
    # LEDS select
    dev.regs.LEDS_MUX_0 = 1

    stat = do_sdramtests(dev, tests = [3])
    if stat != -1:
        print("SDRAM test failed on test %d\n" % stat)
    else:
        print("SDRAM test passed")

    dev.regs.LEDS_MUX_0 = 0


def sniffer_print_statistics(dev, elapsed_time):
    """ Print statistics for the sniff operation during its run. """

    if (int(elapsed_time * 10) % 10) != 0:
        return

    ring_base = 0
    ring_size = dev.RAM_SIZE_BYTES

    dev.regs.SDRAM_SINK_PTR_READ = 0
    dev.regs.OVF_INSERT_CTL = 0

    rptr = dev.regs.SDRAM_SINK_RPTR
    wptr = dev.regs.SDRAM_SINK_WPTR
    wrap_count = dev.regs.SDRAM_SINK_WRAP_COUNT

    rptr -= ring_base
    wptr -= ring_base

    assert 0 <= rptr <= ring_size
    assert 0 <= wptr <= ring_size

    delta = wptr - rptr
    if delta < 0:
        delta += ring_size

    total = wrap_count * ring_size + wptr
    utilization = delta * 100 / ring_size

    print("%d / %d (%3.2f %% utilization) %d kB | %d overflow, %08x total | R%08x W%08x" %
        (delta, ring_size, utilization, total / 1024,
        dev.regs.OVF_INSERT_NUM_OVF, dev.regs.OVF_INSERT_NUM_TOTAL,
        rptr, wptr
        ), file = sys.stderr)

    dev.regs.OVF_INSERT_CTL = 0
    print("%d overflow, %08x total" % (dev.regs.OVF_INSERT_NUM_OVF, dev.regs.OVF_INSERT_NUM_TOTAL), file = sys.stderr)



def output_handler_for_format(format, speed, out):
    """ Return an output handler for the user-provided format. """

    if format == "custom":
        output_handler = OutputCustom(out or sys.stdout, speed)
    elif format == "pcap":
        assert out, "can't output pcap to stdout, use --out"
        output_handler = OutputPcap(out)
    elif format == "iti1480a":
        output_handler = OutputITI1480A(out, speed)
    elif (not format) or (format == "verbose"):
        output_handler = USBSimplePrintSink(speed.is_high_speed())
    else:
        raise ValueError("invalid output format '{}'".format(format))

    return output_handler



@command('sniff', ('speed', str), ('format', str, 'verbose'), ('out', str, None), ('timeout', int, None))
def sniff(dev, speed, format, out, timeout):

    def should_halt(elapsed_time):
        """ Simple callback function that determines if our capture should end. """

        # Halt if we've exceeded the user timeout.
        return (elapsed_time > timeout) if timeout else False


    # Convert the speed into an OV constant.
    try:
        speed_lookup = {
            'hs': OVCaptureUSBSpeed.HIGH,
            'fs': OVCaptureUSBSpeed.FULL,
            'ls': OVCaptureUSBSpeed.LOW
        }
        speed = speed_lookup[speed]
    except KeyError:
        raise ValueError("invalid speed; must be ls, fs, or hs")


    if out:
        out = open(out, "wb")

    # Create an output handler packet sink for the user-provided format.
    try:
        output_handler = output_handler_for_format(format, speed, out)

        # Attach our output handler to the device, and run it.:
        dev.register_sink(output_handler)
        dev.run_capture(speed, halt_callback=should_halt, statistics_callback=sniffer_print_statistics)

    except KeyboardInterrupt:
        dev.ensure_capture_stopped()
    finally: 
        
        # Finally, clean up.
        if out is not None:
            out.close()



@command('debug-stream')
def debug_stream(dev):
    cons = dev.regs.CSTREAM_CONS_LO | dev.regs.CSTREAM_CONS_HI << 8
    prod_hd = dev.regs.CSTREAM_PROD_HD_LO | dev.regs.CSTREAM_PROD_HD_HI << 8
    prod = dev.regs.CSTREAM_PROD_LO | dev.regs.CSTREAM_PROD_HI << 8
    size = dev.regs.CSTREAM_SIZE_LO | dev.regs.CSTREAM_SIZE_HI << 8

    state = dev.regs.CSTREAM_PROD_STATE

    laststart = dev.regs.CSTREAM_LAST_START_LO | dev.regs.CSTREAM_LAST_START_HI << 8
    lastcount = dev.regs.CSTREAM_LAST_COUNT_LO | dev.regs.CSTREAM_LAST_COUNT_HI << 8
    lastpw = dev.regs.CSTREAM_LAST_PW_LO | dev.regs.CSTREAM_LAST_PW_HI << 8

    print("cons: %04x prod-wr: %04x prod-hd: %04x size: %04x state: %02x" % (cons, prod, prod_hd, size, state))
    print("\tlaststart: %04x lastcount: %04x (end: %04x) pw-at-write: %04x" % (laststart, lastcount, laststart + lastcount, lastpw))


@command('ioread', ('addr', str))
def ioread(dev, addr):
    print("%s: %02x" % (addr, dev.read_io_byte(addr)))

@command('iowrite', ('addr', str), ('value', int16))
def iowrite(dev, addr, value):
    dev.write_io_byte(addr, value)

@command('led-test', ('v', int16))
def ledtest(dev, v):
    dev.regs.leds_out = v

@command('eep-erase')
def eeperase(dev):
    dev.ftdi.eeprom_erase()

@command('eep-program', ('serialno', int))
def eepprogram(dev, serialno):
    dev.ftdi.eeprom_program(serialno)

@command('sdram_host_read_test')
def sdram_host_read_test(dev):

    ring_base = 0x10000
    ring_end = ring_base + 1024*1024

    dev.regs.SDRAM_SINK_RING_BASE = ring_base
    dev.regs.SDRAM_SINK_RING_END = ring_end

    dev.regs.SDRAM_HOST_READ_RING_BASE = ring_base
    dev.regs.SDRAM_HOST_READ_RING_END = ring_end

    cnt = 0
    while True:
        rptr = dev.regs.SDRAM_HOST_READ_RPTR_STATUS
        cnt += 1
        if cnt == 5:
            print("GO SINK")
            dev.regs.SDRAM_SINK_GO = 1
        if cnt == 10:
            print("GO SOURCE")
            dev.regs.SDRAM_HOST_READ_GO = 1

        print("rptr = %08x i_stb=%08x i_ack=%08x d_stb=%08x d_term=%08x s0=%08x s1=%08x s2=%08x | wptr = %08x i_stb=%08x i_ack=%08x d_stb=%08x d_term=%08x s0=%08x s1=%08x s2=%08x wrap=%x" % (
            rptr,
            dev.regs.SDRAM_HOST_READ_DEBUG_I_STB,
            dev.regs.SDRAM_HOST_READ_DEBUG_I_ACK,
            dev.regs.SDRAM_HOST_READ_DEBUG_D_STB,
            dev.regs.SDRAM_HOST_READ_DEBUG_D_TERM,
            dev.regs.SDRAM_HOST_READ_DEBUG_S0,
            dev.regs.SDRAM_HOST_READ_DEBUG_S1,
            dev.regs.SDRAM_HOST_READ_DEBUG_S2,
            dev.regs.SDRAM_SINK_WPTR,
            dev.regs.SDRAM_SINK_DEBUG_I_STB,
            dev.regs.SDRAM_SINK_DEBUG_I_ACK,
            dev.regs.SDRAM_SINK_DEBUG_D_STB,
            dev.regs.SDRAM_SINK_DEBUG_D_TERM,
            dev.regs.SDRAM_SINK_DEBUG_S0,
            dev.regs.SDRAM_SINK_DEBUG_S1,
            dev.regs.SDRAM_SINK_DEBUG_S2,
            dev.regs.SDRAM_SINK_WRAP_COUNT,
            ), file = sys.stderr)

        if cnt == 20:
            print("STOP")
            dev.regs.SDRAM_HOST_READ_GO = 0
#            print("STOP: %d" % dev.regs.SDRAM_HOST_READ_GO)


class LB_Test(Command):
    name = "lb-test"

    @staticmethod
    def setup_args(sp):
        sp.add_argument("size", type=int, default=64, nargs='?')

    @staticmethod
    def go(dev, args):
        # Stop the generator - do twice to make sure
        # theres no hanging packet 
        dev.regs.RANDTEST_CFG = 0
        dev.regs.RANDTEST_CFG = 0

        # LEDs off
        dev.regs.LEDS_MUX_2 = 0
        dev.regs.LEDS_OUT = 0

        # LEDS 0/1 to FTDI TX/RX
        dev.regs.LEDS_MUX_0 = 2
        dev.regs.LEDS_MUX_1 = 2

        # Set test packet size
        dev.regs.RANDTEST_SIZE = args.size

        # Reset the statistics counters
        dev.lfsrtest.reset()

        # Start the test (and reinit the generator)
        dev.regs.RANDTEST_CFG = 1

        st = time.time()
        try:
            while 1:
                time.sleep(1)
                b = dev.lfsrtest.stats()
                print("%4s %20d bytes %f MB/sec average" % (
                    "ERR" if b.error else "OK", 
                    b.total, b.total/float(time.time() - st)/1024/1024))

        except KeyboardInterrupt:
            dev.regs.randtest_cfg = 0


def min_version_check(major, minor):
    error_msg = 'ERROR: I depend on behavior in Python {0}.{1} or greater'
    if sys.version_info < (major, minor):
        sys.exit(error_msg.format(major, minor))


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", "-p", type=OVFirmwarePackage, default=default_package)
    ap.add_argument("-l", "--load", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--config-only", "-C", action="store_true")

    # Bind commands
    subparsers = ap.add_subparsers()
    for i in Command.__subclasses__():
        sp = subparsers.add_parser(i.name)
        i.setup_args(sp)
        sp.set_defaults(hdlr=i)

    args = ap.parse_args()

    dev = OVDevice(firmware_package=args.pkg, verbose=args.verbose)

    try:
         dev.open(reconfigure_fpga=args.load)
    except IOError as e:
        if e.errno == -4:
            print("USB: Unable to find device")
            return 1
        print("USB: Error opening device (1)\n")

    print("device open")

    if not dev.fpga_configured(use_cached=True):
        print("FPGA not loaded, forcing reload")
        dev.close()

        try:
            dev.open(reconfigure_fpga=True)
        except IOError:
            print("USB: Error opening device (2)\n")
            return 1

    if args.config_only:
        return

    if not (hasattr(args, 'hdlr') and args.hdlr.name.startswith("eep-")):
        ret = dev.ftdi.eeprom_sanitycheck()
        if ret > 0:
            print("\nPlease run this tool with the subcommand 'eep-program <serial number>'")
            print("to program your EEPROM. The FT2232H FIFO will not work correctly with")
            print("default settings.")
            return 1
        elif ret < 0:
            print("USB: Error checking EEPROM\n")
            return 1

    # ???
    dev.send_packet(b'\x00' * 512)

    try:
        if hasattr(args, 'hdlr'):
            args.hdlr.go(dev, args)
    finally:
        dev.close()

if  __name__ == "__main__":
    min_version_check(MIN_MAJOR, MIN_MINOR)
    main()

