
import struct
import queue
 
from .protocol import OVPacketHandler, OVPacketDispatcher


class ProtocolError(IOError):
    pass


class IOConnection(OVPacketHandler):

    HANDLED_PACKET_NUMBERS = [0x55]
    PACKET_SIZE = 5

    # Flag that indicates a given I/O request is a write request.
    WRITE_REQUEST_FLAG = 0x8000

    def __init__(self, write_handler, memory_window):
        """ Set up a new I/O connection that allows asynchronous read and write requests to be issued to the device.
        
        Args:
            write_handler -- A function used to send bytes to the device.:
        """
        
        self.queue = queue.Queue()
        self.memory_window = memory_window
        super().__init__(write_handler)


    def handle_packet(self, buf):
        """ Handle an asynchronous receipt of an I/O packet. """

        received_checksum = buf[4]
        computed_checksum = sum(buf[0:4]) & 0xFF

        # Validate that the packet contains the correct checksum.
        if computed_checksum != received_checksum:
            raise ProtocolError( "Checksum for response incorrect: expected {:02X}, got {:02X}".format(
                    received_checksum, computed_checksum))

        # And store our response.
        response = (buf[1] << 8 | buf[2], buf[3])
        self.queue.put(response)


    def read(self, address, timeout=None):
        """ Read an I/O register from the OpenVizsla. """

        # For reads, the command is just the I/O address.
        return self._perform_io_request(address, 0, timeout)

    def write(self, address, value, timeout=None):
        """ Read an I/O register from the OpenVizsla. """

        # For writes, the command is the I/O address with its MSB set.
        command = self.WRITE_REQUEST_FLAG | address
        return self._perform_io_request(command, value, timeout)


    def _submit_io_request(self, command, value):
        """ Submits an I/O command to the OpenVizsla. A response should be received aynchronously by handle_packet. """
        
        # Build the I/O request packet...
        packet = [0x55, (command >> 8), command & 0xFF, value]

        # ... append a checksum...
        checksum = (sum(packet) & 0xFF)
        packet.append(checksum)

        # ... and send it to the device.
        self.send(bytes(packet))

    
    def _perform_io_request(self, command, value, timeout):

        # Submit the I/O request to the OpenVizsla device...
        self._submit_io_request(command, value)

        # ... and wait for a result.
        try:
            command_performed, result = self.queue.get(True, timeout)
        except queue.Empty:
            raise TimeoutError("IO access timed out")

        assert command_performed == command

        # Return the relevant result.
        return result



class SDRAMHandler(OVPacketHandler, OVPacketDispatcher):
    """ SDRAM I/O packet handler. """

    HANDLED_PACKET_NUMBERS = [0xd0]
    BYTES_NECESSARY_TO_DETERMINE_SIZE = 2

    def __init__(self, write_handler, verbose=None):
       # Call each of our superclasses.
       OVPacketHandler.__init__(self, write_handler)
       OVPacketDispatcher.__init__(self, verbose=verbose, short_name='SDRAM')

    def _packet_size(self, buf):
        return (buf[1] + 1) * 2 + 2

    def handle_packet(self, packet):
        """ Handle SDRAM packets by passing on packets to their subordinates. """

        # Handle the raw SDRam packet without its header
        self.handle_incoming_bytes(packet[2:])

