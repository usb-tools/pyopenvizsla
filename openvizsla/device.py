"""
Code for interacting with OpenVizsla devices.
"""

import time
import threading

from enum import Enum

from . import OVCaptureUSBSpeed, find_openvizsla_asset

from .ftdi import FTDIDevice
from .memory import OVMemoryWindow, USB334xMemoryWindow

from .sniffer import USBSniffer
from .firmware import OVFirmwarePackage
from .protocol import OVPacketDispatcher, LFSRTest, DummyHandler
from .io import IOConnection, SDRAMHandler

from .libov import FPGA_GetConfigStatus, HW_Init


class OVDevice(OVPacketDispatcher):

    """ Class representing an OpenVizsla device. """

    # Define the size of the OV device's on-board SDRAM capture buffer.
    RAM_SIZE_MIB   = 16
    RAM_SIZE_BYTES = RAM_SIZE_MIB * 1024 * 1024

    # Constants for working with the ULPI UCFG register.
    UCFG_REGISTER_ACCESS_ACTIVE = 0x80
    UCFG_REGISTER_ADDRESS_MASK  = 0x3F

    # Magic number for the USB334X.
    USB334X_DEVICE_ID = 0x4240009

    # Default firmware package name.
    DEFAULT_FIRMWARE_PACKAGE_NAME = 'ov3.fwpkg'


    def __init__(self, firmware_package=None, verbose=False):
        """ Set up -- but do not open -- a connection to an OpenVizsla device. """

        # Set up the OV device to handle packets.
        super().__init__(verbose=verbose)

        # If we weren't handed a firmware package, look for the default.
        if firmware_package is None:
            package_file = find_openvizsla_asset(self.DEFAULT_FIRMWARE_PACKAGE_NAME)
            firmware_package = OVFirmwarePackage(package_file)
       
        self.verbose      = verbose
        self.firmware     = firmware_package

        # Default to being unopened, and assume an unprogrammed FPGA.
        self._is_open     = False
        self._fpga_loaded = False

        # Create the FTDI connection to our OV device.
        self.ftdi         = FTDIDevice()

        # Set up "memory windows" that allow us to access the OV device's I/O and 
        mmio_map          = firmware_package.get_register_map()
        self.regs         = OVMemoryWindow(mmio_map, self.read_io_byte, self.write_io_byte)
        self.ulpi_regs    = USB334xMemoryWindow(self.read_ulpi_register, self.write_ulpi_register)

        # Start off with an unvalidated ULPI clock.
        self.ulpi_clock_validated = False

        # Build our local packet handlers.
        self._set_up_io_handlers()


    def _set_up_io_handlers(self):
        """ Registers the standard packet handler for communicating with OpenVizsla. """

        # Build a simple subordinate write function that's closed over the current device,
        # and which knows how to send data.
        def send(packet):
            self.send_packet(packet)

        # Create our I/O connection and our USB sniffer handlers.
        self.io      = IOConnection(send, self.regs)
        self.sniffer = USBSniffer(send)

        # Create our SDRam read handler, and register our sniffer with it, so stored USB
        # packets can be forwarded to the USB sniffer.
        sdram_handler = SDRAMHandler(send)
        sdram_handler.register_packet_handler(self.sniffer)
        
        # Register our core packet handlers to handle received packets.
        self.register_packet_handler(self.io)
        self.register_packet_handler(LFSRTest(send))
        self.register_packet_handler(self.sniffer)
        self.register_packet_handler(sdram_handler)
        self.register_packet_handler(DummyHandler(send))


    def send_packet(self, raw_packet):
        """ Sends a packet over our FTDI backend. """

        if self.verbose:
            print("< %s" % " ".join("%02x" % i for i in raw_packet))

        # Send the data to the device.
        self.ftdi.write(self.ftdi.INTERFACE_A, raw_packet, async_=False)

    
    def __comms_thread_body(self):
        """ Internal function that executes as our comms thread. """

        # Define a callback that will handle receipt of data.
        def comms_callback(received, prog):
            """ Asynchronous callback issued when the FTDI device receives data. """

            try:
                self.handle_incoming_bytes(received)
                return int(self.__comm_term) 

            except Exception as e:
                self.__comm_term = True
                self.__comm_exc = e
                return 1

        # Repeately try to read from the FTDI device, and handle its results.
        # FIXME: replace the termination object with an threading.Event.
        while not self.__comm_term:
            self.ftdi.read_async(self.ftdi.INTERFACE_A, comms_callback, 8, 16)

        # If a failure occurred in parsing, raise it out of our asynchronous context.
        # TODO: exception should be locked
        if self.__comm_exc:
            raise self.__comm_exc


    def _start_comms_thread(self):
        """ Start the background thread that handles our core communication. """

        self.commthread = threading.Thread(target=self.__comms_thread_body, daemon=True)
        self.__comm_term = False
        self.__comm_exc = None

        self.commthread.start()

        self.__comm_term = False


    def open(self, reconfigure_fpga=False):
        """ Opens a new connection to the OV device, and prepares it for use.
        
        Args:
            reconfigure_fpga -- If true, the FPGA will be configured even if it's already been programmed.:w
        """

        if self._is_open:
            raise ValueError("OVDevice doubly opened")

        # Open our connection to our FTDI device.
        rc = self.ftdi.open()
        if rc:
            error = IOError("couldn't open connection to our USB device!")
            error.errno = rc
            raise error

        # Configure the FPGA, if necessary.
        self.configure_fpga(self.firmware.get_bitstream_file(), not reconfigure_fpga)

        # Start our background thread for comms.
        self._start_comms_thread()

        # Apply our default LED values.
        self._apply_default_leds()

        # Finally, mark ourselves as open.
        self._is_open = True


    def _apply_default_leds(self):
        """ Sets up the default OV led controls for capture. """

        # LEDs off
        self.regs.LEDS_MUX_2 = 0
        self.regs.LEDS_OUT = 0

        # LEDS 0/1 to FTDI TX/RX
        self.regs.LEDS_MUX_0 = 2
        self.regs.LEDS_MUX_1 = 2



    def close(self):
        """ Terminates our connection to the OV device. """

        # If the device has already been closed, we have nothing to do!
        if not self._is_open:
            return

        self.__comm_term = True
        self.commthread.join()

        self.ftdi.close()

        self._is_open = False


    def __del__(self):
        """ Finalizer that well attempt to close the device nicely, if it wasn't already. """

        if self._is_open:
            self.close()


    def _stop_capture_to_ram(self):
        """ Requests that the OV device stop capturing data from USB to its onboard SDRAM. """
        self.regs.SDRAM_SINK_GO = 0


    def _stop_streaming_ram_to_host(self):
        """ Requests that the OV device stop streaming capture data from its SDRAM to the host. """
        self.regs.SDRAM_HOST_READ_GO = 0
        self.regs.CSTREAM_CFG = 0


    def _device_stop_capture(self):
        """ Requests that the device stop all aspects of capture. """

        # TODO: we may want to provide an option to flush the SDRam buffer here before capture stops?
        self._stop_capture_to_ram()
        self._stop_streaming_ram_to_host()


    def _initialize_sdram_ringbuffer(self, ringbuffer_size=None, ringbuffer_base=0):
        """ Initialize the ringbuffer, and """

        # If no ringbuffer size is provided, use the full size of the SDRAM.
        if ringbuffer_size is None:
            ringbuffer_size = self.RAM_SIZE_BYTES

        # Figure out the extents of the ringbuffer in RAM.
        ringbuffer_end  = ringbuffer_base + ringbuffer_size

        # Ensure the SDRAM isn't being used as either a source _or_ sink,
        # by ensuring it's neither capturing USB data to the SDRAM nor 
        # streaming SDRAM contents to the host.
        self._stop_capture_to_ram()
        self._stop_streaming_ram_to_host()

        # Reset the ringbuffer extents, and its 
        self.regs.SDRAM_SINK_RING_BASE      = ringbuffer_base
        self.regs.SDRAM_SINK_RING_END       = ringbuffer_end
        self.regs.SDRAM_HOST_READ_RING_BASE = ringbuffer_base
        self.regs.SDRAM_HOST_READ_RING_END  = ringbuffer_end



    def _start_capture_to_ram(self):
        """ Instruct the OV device to begin capturing USB data to the on-board SDRam. """
        self.regs.SDRAM_SINK_GO = 1


    def _start_streaming_ram_to_host(self):
        """ Instruct the OV device to begin streaming its captured data to the host. """
        self.regs.SDRAM_HOST_READ_GO = 1
        self.regs.CSTREAM_CFG = 1


    def _device_start_capture(self):
        """ Requests that the device start a USB capture on its side. """

        # TODO: we may want to provide an option to flush the SDRam buffer here before capture stops?
        self._start_capture_to_ram()
        self._start_streaming_ram_to_host()


    def _initialize_performance_counters(self):
        """ Reset the device's on-board performance counters. """
        self.regs.OVF_INSERT_CTL = 1
        self.regs.OVF_INSERT_CTL = 0


    def _set_up_phy_for_capture(self, usb_speed):
        """ Set up the PHY for a USB capture.

        Args:
            usb_speed -- The USB speed the communication is known to be operating at.
        """

        # Set up our ULPI PHY's core functionality: set it powered on, in non-driving mode
        # (so we can snoop), and set the relevant speed.
        self.ulpi_regs.FUNC_CTL = \
            int(usb_speed) | self.ulpi_regs.FuncCTLFlags.OPERATING_MODE_NON_DRIVING \
            | self.ulpi_regs.FuncCTLFlags.PHY_POWERED


    def register_sink(self, event_sink):
        """ Registers a USBEventSink to receive any USB events. 
        
        Args:
            event_sink -- The sniffer.USBEventSink object to receive any USB events that occur.
        """
        self.sniffer.register_sink(event_sink)



    def run_capture(self, usb_speed, statistics_callback=None, statistics_period=0.1, halt_callback=lambda _ : False, ):
        """ Runs a USB capture from an OpenVizsla device. 
        
        Args:
            usb_speed -- The USB speed the communication is believed to be operating at.
                In the future, this should hopefully be somewhat auto-detectable, and this
                argument will be optional; but for now it must be provided.
        """

        # Set up the device for capture.
        self._initialize_sdram_ringbuffer()
        self._set_up_phy_for_capture(usb_speed)

        # Start a capture on the device.
        self._device_start_capture()

        elapsed_time = 0.0
        try:

            # Continue until the user-supplied halt condition is met.
            while not halt_callback(elapsed_time): 

                # If we have a statistics callback, call it.
                if callable(statistics_callback):
                    statistics_callback(self, elapsed_time)

                # Wait for the next statistics-interval to occur.
                time.sleep(statistics_period)
                elapsed_time = elapsed_time + statistics_period

        finally:
            self._device_stop_capture()


    def ensure_capture_stopped(self):
        """ Ensure that any running USBcapture has been cleanly terminated. """

        self._device_stop_capture()


    def fpga_configured(self, use_cached=False):
        """ Returns true iff we know the current FPGA is programmed. """

        assert self._is_open

        if use_cached:
            return self._fpga_loaded
        else:
            self._fpga_loaded = (FPGA_GetConfigStatus(self.ftdi) == 0)
            return self._fpga_loaded


    def configure_fpga(self, bitstream, skip_if_configured=False):
        """ Programs the provided bitstream into the device's FPGA. """

        fpga_configured = (FPGA_GetConfigStatus(self.ftdi) == 0)

        # If the FPGA is already configured, and we're allowed to skip configuration, skip it!
        if skip_if_configured and fpga_configured:
            self._use_existing_configuration()
            return


        # If the bitstream is a file-like object, use it.
        if not isinstance(bitstream, bytes) and hasattr(bitstream, 'read'):

            # FIXME: Current bit_file code is heavily dependent on fstream ops
            #  and isn't nice to call with a python file-like object
            #
            # Workaround this by emitting a tempfile
            import tempfile
            import os

            bitfile = tempfile.NamedTemporaryFile(delete=False)

            try:
                bitfile.write(bitstream.read())
                bitfile.close()

                HW_Init(self.ftdi, bitfile.name.encode('ascii'))
                self._fpga_loaded = True
           
            finally:
                # Make sure we cleanup the tempfile
                os.unlink(bitfile.name)

        # Otherwise, if we have a set of raw bytes, upload that.:
        elif isinstance(bitstream, bytes):
            HW_Init(self.ftdi, bitstream)
            self._fpga_loaded = True

        else:
            raise TypeError("bitstream must be bytes or file-like")


    def _use_existing_configuration(self):
        """ Attempts to initialize our hardware using the FPGA's existing configuration. """
        HW_Init(self.ftdi, None)


    def ulpi_clock_is_up(self):
        """ Returns true iff the FPGA reports the ULPI as being up. """
        
        if self.ulpi_clock_validated:
            return True

        self.ulpi_clock_validated = bool(self.regs.ucfg_stat & 0x1)

        return self.ulpi_clock_validated


    def read_ulpi_register(self, addr):
        """ Reads the value of a ULPI register, by address. You likely want to touch the ulpi_regs view instead. """
        assert self.ulpi_clock_is_up()

        self.regs.ucfg_rcmd = self.UCFG_REGISTER_ACCESS_ACTIVE | (addr & self.UCFG_REGISTER_ADDRESS_MASK)

        while self.regs.ucfg_rcmd & self.UCFG_REGISTER_ACCESS_ACTIVE:
            pass

        return self.regs.ucfg_rdata


    def write_ulpi_register(self, address, value):
        """ Writes the value of a ULPI register, by address. You likely want to touch the .ulpi_regs attribute instead.  """

        assert self.ulpi_clock_is_up()

        self.regs.ucfg_wdata = value
        self.regs.ucfg_wcmd  = self.UCFG_REGISTER_ACCESS_ACTIVE | (address & self.UCFG_REGISTER_ADDRESS_MASK)
        
        while self.regs.ucfg_wcmd & self.UCFG_REGISTER_ACCESS_ACTIVE:
            pass


    def read_io_byte(self, address):
        """ Reads a byte from the I/O address space, by address. You likely want to touch the .regs attribute instead"""
        return self.io.read(self.regs.resolve_address(address))


    def write_io_byte(self, address, value):
        """ Writes a byte to the I/O address space, by address. You likely want to touch the .regs attribute instead"""
        return self.io.write(self.regs.resolve_address(address), value)
