"""
Memory mapping functions.
"""

from enum import IntFlag

class OVMemoryWindow:
    """ Class representing a window into an address space on the OpenVizsla board. """


    class OVRegister:
        """ Class representing a single register in an OV memory window. """

        def __init__(self, window, name, address, size):
            """ Set up the MMIO register. """

            self.window  = window
            self.address = address
            self.size    = size
            self.name    = name


        def read(self):
            """ Read the register's value from the OpenVizsla device. """
            shadow = 0

            # Read our register byte by byte.
            for i in range(self.size):
                shadow <<= 8
                shadow |= self.window.read(self.address + i)

            return shadow


        def write(self, value):
            """ Write the register's value in the OpenVizsla device. """

            # Write our register byte by byte.
            for i in range(self.size):
                value_to_write = (value >> (i * 8)) & 0xFF
                self.window.write(self.address + self.size - 1 - i, value_to_write)


        def __repr__(self):
            addr_range = "-{:04x}".format(self.address + (self.size - 1)) if self.size > 1 else ""
            return "<OVRegister {}@{:04x}{}>".format(self.name, self.address, addr_range)



    def __init__(self, memory_map, byte_read_function, byte_write_function):
        
        # Store our byte_read_function and our byte_write_function, for later use.
        self.__dict__['read']  = byte_read_function
        self.__dict__['write'] = byte_write_function

        # Process our memory map, and generate a collection of register objects.
        registers = {}

        # Iterate over each of the items in our memory map, and add them our register list.
        for name, (addr, size) in memory_map.items():
            registers[name] = self.OVRegister(self, name, addr, size)

        # Finally, store our register collection.
        self.__dict__['registers'] = registers


    def __getattr__(self, attr):
        """
        If we've been asked for an attribute we don't have, interpret it as a register name,
        and read the relevant register's value.
        """

        normalized_name = attr.upper()

        try:
            return self.registers[normalized_name].read()
        except KeyError:
            raise AttributeError("tried to read from an unknown register {}".format(attr))


    def __setattr__(self, attr, value):
        """
        If we've been asked to set an attribute we don't have, interpret it as a register name,
        and write to the releveant register.
        """

        normalized_name = attr.upper()

        try:
            return self.registers[normalized_name].write(value)
        except KeyError:
            raise AttributeError("tried to write to an unknown register {}".format(attr))


    def resolve_address(self, symbol):
        """ Attempts to resolve a symbol in the given memory space to an address. 
        
        Args:
            symbol -- A register name, or anything that parses to an int.
        Returns: the address associated with the given symbol
        """
        
        # If we already have an integer, return it directly.
        if isinstance(symbol, int):
            return symbol


        # If the number makes sense in base 16, return that.
        # TODO: is this the best way to handle string-nums?
        try:
            return int(symbol, 16)
        except ValueError:
            pass


        # Otherwise, try to look up the name in our register map.
        try:
            normalized_name = symbol.upper()
            return self.registers[normalized_name].address
        except KeyError:
            pass

        raise ValueError("could not resolve symbol {}".format(symbol))


    def look_up_symbol(self, address):
        """ Looks up the symbol for a given address. """

        # Iterate over every register and look for a name.
        for name, register in self.registers.items():

            # If this register matches exactly, return it.
            if register.address == address:
                return "{}/0x{:02x}".format(name, address)

        # Otherwise, just return the address as a hex string.
        return  "{:02x}".format(address)



class USB334xMemoryWindow(OVMemoryWindow):
    """ Memory window for accessing ULPI phy registers on a USB3334x. """


    class FuncCTLFlags(IntFlag):
        """ Flag values for a ULPI phy's FUNC_CTL register. """

        # Control over the PHY's power and reset.
        PHY_POWERED = 1 << 6
        PHY_RESET   = 1 << 5

        # Control over the PHY's operating mode.
        # We usually want non-driving, as we want to act as a sniffer,
        # and not actively participate in USB.
        OPERATING_MODE_NORMAL       = (0b00 << 3)
        OPERATING_MODE_NON_DRIVING  = (0b01 << 3)
        OPERATING_MODE_UNENCODED    = (0b10 << 3)
        OPERATING_MODE_MANUAL       = (0b11 << 3)

        # Control over the PHY's internal termination resistors.
        APPLY_TERMINATION_RESISTORS = 1 << 2



    REGISTER_ADDRESSES = {
        "VIDL": 0x00,
        "VIDH": 0x01,
        "PIDL": 0x02,
        "PIDH": 0x03,

        "FUNC_CTL": 0x04,
        "FUNC_CTL_SET": 0x05,
        "FUNC_CTL_CLR": 0x06,

        "INTF_CTL": 0x07,
        "INTF_CTL_SET": 0x08,
        "INTF_CTL_CLR": 0x09,

        "OTG_CTL": 0x0A,
        "OTG_CTL_SET": 0x0B,
        "OTG_CTL_CLR": 0x0C,

        "USB_INT_EN_RISE": 0x0D,
        "USB_INT_EN_RISE_SET": 0x0e,
        "USB_INT_EN_RISE_CLR": 0x0f,

        "USB_INT_EN_FALL": 0x10,
        "USB_INT_EN_FALL_SET": 0x11,
        "USB_INT_EN_FALL_CLR": 0x12,

        "USB_INT_STAT": 0x13,
        "USB_INT_LATCH": 0x14,

        "DEBUG": 0x15,

        "SCRATCH": 0x16,
        "SCRATCH_SET": 0x17,
        "SCRATCH_CLR": 0x18,

        "CARKIT": 0x19,
        "CARKIT_SET": 0x1A,
        "CARKIT_CLR": 0x1B,

        "CARKIT_INT_EN": 0x1D,
        "CARKIT_INT_EN_SET": 0x1E,
        "CARKIT_INT_EN_CLR": 0x1F,

        "CARKIT_INT_STAT": 0x20,
        "CARKIT_INT_LATCH": 0x21,

        "HS_COMP_REG":   0x31,
        "USBIF_CHG_DET": 0x32,
        "HS_AUD_MODE":   0x33,

        "VND_RID_CONV": 0x36,
        "VND_RID_CONV_SET": 0x37,
        "VND_RID_CONV_CLR": 0x38,

        "USBIO_PWR_MGMT": 0x39,
        "USBIO_PWR_MGMT_SET": 0x3A,
        "USBIO_PWR_MGMT_CLR": 0x3B,
    }


    def __init__(self, byte_read_function, byte_write_function):

        memory_map = {}

        # Build a memory map where every register is of size '1'.
        for name, addr in self.REGISTER_ADDRESSES.items():
            memory_map[name] = (addr, 1)

        # And create our base window
        super().__init__(memory_map, byte_read_function, byte_write_function)

