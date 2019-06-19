"""
Code for interacting with OpenVizsla devices.
"""

import threading

from .ftdi import FTDIDevice
from .memory import OVMemoryWindow, USB334xMemoryWindow

from .sniffer import USBSniffer
from .protocol import OVPacketDispatcher, LFSRTest, DummyHandler
from .io import IOConnection, SDRAMHandler

from .libov import FPGA_GetConfigStatus, HW_Init


class OVDevice(OVPacketDispatcher):

    """ Class representing an OpenVizsla device. """

    UCFG_REGISTER_ACCESS_ACTIVE = 0x80
    UCFG_REGISTER_ADDRESS_MASK  = 0x3F

    # Magic number for the USB334X.
    USB334X_DEVICE_ID = 0x4240009


    def __init__(self, firmware_package=None, verbose=False):
        """ Set up -- but do not open -- a connection to an OpenVizsla device. """

        # Set up the OV device to handle packets.
        super().__init__(verbose=verbose)
       
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

        # Finally, mark ourselves as open.
        self._is_open = True


    def close(self):
        """ Terminates our connection to the OV device. """

        if not self._is_open:
            raise ValueError("OVDevice doubly closed")

        self.__comm_term = True
        self.commthread.join()

        self.ftdi.close()

        self._is_open = False


    def __del__(self):
        """ Finalizer that well attempt to close the device nicely, if it wasn't already. """

        if self._is_open:
            self.close()


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
