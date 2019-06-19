import ctypes

from . import libov_native

# Get a refernce to the native libov DLL.
libov = ctypes.cdll.LoadLibrary(libov_native.__file__)

#
# FIXME: move most of this into python.c in libov, so libov presents a valid python interface
# 

class FTDI_Device(ctypes.Structure):
    _fields_ = [
                ('_1', ctypes.c_void_p),
                ('_2', ctypes.c_void_p),
                ]

pFTDI_Device = ctypes.POINTER(FTDI_Device)

# FTDIDevice_Open
FTDIDevice_Open = libov.FTDIDevice_Open
FTDIDevice_Open.argtypes = [pFTDI_Device]
FTDIDevice_Open.restype = ctypes.c_int

# FTDIDevice_Close
FTDIDevice_Close = libov.FTDIDevice_Close
FTDIDevice_Close.argtypes = [pFTDI_Device]

FTDIDevice_Write = libov.FTDIDevice_Write
FTDIDevice_Write.argtypes = [
        pFTDI_Device, # Dev
        ctypes.c_int, # Interface
        ctypes.c_char_p, # Buf
        ctypes.c_size_t, # N
        ctypes.c_bool, # async
        ]
FTDIDevice_Write.restype = ctypes.c_int

p_cb_StreamCallback = ctypes.CFUNCTYPE(
        ctypes.c_int,    # retval
        ctypes.POINTER(ctypes.c_uint8), # buf
        ctypes.c_int, # length
        ctypes.c_void_p, # progress
        ctypes.c_void_p) # userdata

FTDIDevice_ReadStream = libov.FTDIDevice_ReadStream
FTDIDevice_ReadStream.argtypes = [
        pFTDI_Device,    # dev
        ctypes.c_int,    # interface
        p_cb_StreamCallback, # callback
        ctypes.c_void_p, # userdata
        ctypes.c_int, # packetsPerTransfer
        ctypes.c_int, # numTransfers
        ]
FTDIDevice_ReadStream.restype = ctypes.c_int

# void ChandlePacket(unsigned int ts, unsigned int flags, unsigned char *buf, unsigned int len)
ChandlePacket = libov.ChandlePacket
ChandlePacket.argtypes = [
    ctypes.c_ulonglong, # ts
    ctypes.c_int, # flags
    ctypes.c_char_p, # buf
    ctypes.c_int, # len
]

# int FTDIEEP_Erase(FTDIDevice *dev)
FTDIEEP_Erase = libov.FTDIEEP_Erase
FTDIEEP_Erase.argtypes = [
        pFTDI_Device,    # dev
        ]
FTDIEEP_Erase.restype = ctypes.c_int

# int FTDIEEP_CheckAndProgram(FTDIDevice *dev, unsigned int number)
FTDIEEP_CheckAndProgram = libov.FTDIEEP_CheckAndProgram
FTDIEEP_CheckAndProgram.argtypes = [
        pFTDI_Device,    # dev
        ctypes.c_int,    # serial number
        ]
FTDIEEP_CheckAndProgram.restype = ctypes.c_int

# int FTDIEEP_SanityCheck(FTDIDevice *dev, bool verbose)
FTDIEEP_SanityCheck = libov.FTDIEEP_SanityCheck
FTDIEEP_SanityCheck.argtypes = [
        pFTDI_Device,    # dev
        ctypes.c_bool,   # verbose
        ]
FTDIEEP_SanityCheck.restype = ctypes.c_int

_FPGA_GetConfigStatus = libov.FPGA_GetConfigStatus
_FPGA_GetConfigStatus.restype = ctypes.c_int
_FPGA_GetConfigStatus.argtypes = [pFTDI_Device]

def FPGA_GetConfigStatus(dev):
    return _FPGA_GetConfigStatus(dev._dev)

_HW_Init = libov.HW_Init
_HW_Init.argtypes = [pFTDI_Device, ctypes.c_char_p]

def HW_Init(dev, bitstream):
    return _HW_Init(dev._dev, bitstream)
