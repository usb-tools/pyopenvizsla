"""
OpenVZ services -- asynchronous objects that exchange data to/from the device
"""

import collections
from enum import Enum


class IncompletePacket(IOError):
    """ Exception used if we attempt to parse a packet that's insufficiently long to parse. """
    pass


class InappropriatePacket(IOError):
    """ Exception used if we attempt to parse a packet that's not appropriate for our handler."""
    pass


class OVPacketDispatcher:
    """
    Mix-in for a class that receves packets and then delegates to subordinate packet handlers.
    """

    def __init__(self, verbose=False, short_name=''):
        """ Set up our PacketDispatcher. """

        self.verbose = verbose
        self.short_name = short_name

        # Create a new empty bytearray to store buffers.
        self._buffer = bytearray()

        # And create a new list of packet handlers.
        self._packet_handlers = []


    def register_packet_handler(self, handler):
        """ Registers a new packet handler for the OpenVizsla comms. """
        self._packet_handlers.append(handler)


    def handle_incoming_bytes(self, raw):
        """ Handles receipt of new bytes from an I/O channel. """

        USE_STRICT_HANDLING = True

        incomplete = False

        if self.verbose and raw:
            hexdump = " ".join("{:02X}".format(i) for i in raw)
            print("{}> {}".format(self.short_name, hexdump))

        # Add the rx'd bytes to our buffer.
        self._buffer += raw

        # Dispatch all of the bytes we have -- noting that we may have bytes for multiple packets.
        while self._buffer and not incomplete:
            bytes_handled = 0

            # Give each of our handlers the opportunity to parse the current data.
            for handler in self._packet_handlers:
                try:
                    bytes_handled = handler.handle_bytes_received(self._buffer)
                except IncompletePacket:
                    incomplete = True
                    continue
                except InappropriatePacket:
                    continue

                # Consume the relevant number of bytes read...
                if bytes_handled:

                    if self.verbose:
                        print(" ---- {} handled {} ({} bytes remain)".format(
                            type(handler).__name__, self._buffer[0:bytes_handled], len(self._buffer) - bytes_handled))

                    self._buffer = self._buffer[bytes_handled:]
                    break


                if USE_STRICT_HANDLING:
                    raise IOError("{}> unmatched byte {:02x} in I/O stream!".format(self.short_name, discarded))
                else:
                    print("{}> unmatched byte {:02x} - discarding".format(self.short_name, discarded))




class OVPacketHandler:
    """
    Class representing an asynchronous data transmission/receipt service.
    Typically each service handles a specific kind of packet from the OV device.
    """

    # Subclasses should override this variable.
    # Lists the packet types a given service handles.
    HANDLED_PACKET_NUMBERS = []

    # If the packet size for the given service isn't fixed, the subclass should
    # override this variable with the number of bytes necessary to determine that.
    # If that isn't fixed, the subclass should overide `bytes_necessary_to_determine_size`.
    BYTES_NECESSARY_TO_DETERMINE_SIZE = 1


    # If the packet has a fixed size, the subclass can override this variable
    # to set the packet's size. Otherwise, it can override _packet_size to
    # parse the given packet and generate its size.
    PACKET_SIZE = None


    def __init__(self, write_handler):
        """ Set up the a OV packet handler. 
        
        Args:
            write_handler -- A function that accepts a list of bytes, and sends them down to the OpenVizsla device.
        """
        self._write_handler = write_handler


    def handles_packet_number(self, packet_number):
        """ Returns true iff this handler accepts the given magic number. """
        return packet_number in self.HANDLED_PACKET_NUMBERS


    def bytes_necessary_to_determine_size(self, magic_number):
        """ Returns the number of bytes necessary to determine the packet's size. """
        return self.BYTES_NECESSARY_TO_DETERMINE_SIZE


    def packet_size(self, data):
        """
        Returns the size of the packet represented by the given data, 
        or None if it can't (yet) be determined.
        """

        if len(data) < self.bytes_necessary_to_determine_size(data[0]):
            return None

        return self._packet_size(data)


    def _packet_size(self, data):
        """ Returns the size of the packet accepted by the given class. """
        return self.PACKET_SIZE


    def handle_packet(self, data):
        """ Handle the given packet. """
        raise NotImplementedError("Packet handlers must define handle_packet.")


    def handle_bytes_received(self, data):
        """ Attempts to handle a set of bytes received from the OpenVizsla. """

        if len(data) < 1:
            raise IncompletePacket()

        # If the given packet isn't handled by this class, return that this class
        # is an inappropriate handler.
        if not self.handles_packet_number(data[0]):
            raise InappropriatePacket()

        # Check to see if we have a full packet. If we don't, return that things
        # are still incomplete.
        size = self.packet_size(data)
        if (size is None) or (len(data) < size):
            raise IncompletePacket()

        # Handle the given packet...
        self.handle_packet(data[:size])

        # ... and return the amount of data we've consumed.
        return size


    def send(self, data):
        """ Sends a set of bytes to the OpenVizsla. """
        self._write_handler(data)


# Basic Test service for testing stream rates and ordering
# Ideally we'd verify the entire LFSR, but python is too slow
# As it is, the rates are CPU-bound.
class LFSRTest(OVPacketHandler):
    _stats = collections.namedtuple('LFSR_Stat', ['total', 'error'])

    HANDLED_PACKET_NUMBERS = [0xAA]
    BYTES_NECESSARY_TO_DETERMINE_SIZE = 2

    def __init__(self, write_handler):
        self.total = 0
        self.reset()
        super().__init__(write_handler)

    def reset(self):
        self.state = None
        self.error = 0
        self.total = 0

    def _packet_size(self, buf):
        # overhead is magic, length
        return buf[1] + 2


    def handle_packet(self, buf):
        assert buf[0] == self.HANDLED_PACKET_NUMBERS[0]
        assert buf[1] + 2 == len(buf)

        self.total += buf[1]

        if self.state != None:
            if buf[2] & 0xFE != (self.state << 1) & 0xFE:
                self.error = 1

        self.state = buf[-1]


    def stats(self):
        return self._stats(total=self.total, error=self.error)



class DummyHandler(OVPacketHandler):
    """ Consumes packets we have no need to handle. """

    HANDLED_PACKET_NUMBERS = [0xe0, 0xe8]
    PACKET_SIZE = 3

    def handle_packet(self, buf):
        assert ''.join("%02x"% r for r in buf) in ["e0e1e2", "e8e9ea"], buf







