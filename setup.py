try:
    import pkgconfig
except:
    pass

from setuptools import setup, find_packages, Extension

# The sources necessary to build libov.
# TODO: add gettimeofday.c if we're on Windows.
libov_sources = [
        'libov/bit_file.c',
        'libov/fastftdi.c',
        'libov/fpgaconfig.c',
        'libov/ftdieep.c',
        'libov/hw_common.c',
        'libov/usb_interp.c',
        'libov/python.c'
]

# Describe how to build libov, the native-code component of the openvizsla library.
libov = Extension('openvizsla.libov_native', 
    sources=libov_sources,
    **pkgconfig.parse('libusb-1.0')
)


setup(
    name='pyopenvizsla',
    version='0.0.1',
    python_requires='>3.3',
    url='https://github.com/usb-tools/pyopenvizsla',
    license='MIT',
    entry_points = {
        'console_scripts': [ 
            'ovctl = openvizsla.commands.ovctl:main',
            'ov_sniff = openvizsla.commands.ov_sniff:main',
        ]
    },
    tests_require=[''],
    setup_requires=['pkgconfig'],
    install_requires=['crcmod'],
    description='Python library for interfacing with OpenVizsla logic analyzers',
    long_description='Python library for interfacing with OpenVizsla logic analyzers; intended to all modular use of libOV in other programs',
    ext_modules = [libov],
    packages=find_packages(),
    include_package_data=True,
    platforms='any',
    classifiers = [
        'Programming Language :: Python',
        'Development Status :: 1 - Planning',
        'Natural Language :: English',
        'Environment :: Console',
        'Environment :: Plugins',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Topic :: Scientific/Engineering',
        'Topic :: Security',
        ],
    extras_require={}
)
