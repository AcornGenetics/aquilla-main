import spidev
import time

# ADS7124

#  CS               1
#  SDIN             2
#  SDO              3
#  SCLK             4
#  GND              5, 11
#  IOVDD            6, 12
#  SDO              7
#  Open or SDO      8
#  Open or SDO      9
#  Open or SDO     10

# SPI configuration
SPI_BUS = 0  # SPI bus number (e.g., 0 for SPI0)
SPI_DEVICE = 0  # Chip Select (CS) line (e.g., 0 for CE0)
SPI_SPEED_HZ = 614000  # SPI clock speed in Hz

# AD7124-8 Register Addresses (simplified example)
# You would need to refer to the AD7124-8 datasheet for full register map
REG_STATUS = 0x00

REG_ADC_CONTROL = 0x01
REG_DATA = 0x02

# Initialize SPI
spi = spidev.SpiDev()
spi.open(SPI_BUS, SPI_DEVICE)
spi.max_speed_hz = SPI_SPEED_HZ

#spi.writebytes( [0xFF]*8 )
#time.sleep ( 1 )

def read_register(register_address, num_bytes):
    """Reads data from a specified AD7124-8 register."""
    # The first byte is the read command + register address
    # AD7124-8 communication protocol specifies how to form this byte
    # Example: 0x40 for read, then register address
    command_byte = 0x40 | register_address
    rx_data = spi.xfer2([command_byte] + [0x00] * num_bytes)
    return rx_data[1:] # Return data bytes, excluding the command byte

def write_register(register_address, data_bytes):
    """Writes data to a specified AD7124-8 register."""
    # The first byte is the write command + register address
    # Example: 0x00 for write, then register address
    command_byte = 0x00 | register_address
    spi.xfer2([command_byte] + data_bytes)

def read_adc_data():
    """Reads the ADC conversion result."""
    # Assuming the ADC is configured to continuously convert
    # and data is available in the DATA register
    data_bytes = read_register(REG_DATA, 3) # AD7124-8 is 24-bit, so 3 bytes
    # Convert bytes to an integer (signed 24-bit)
    adc_value = int.from_bytes(data_bytes, byteorder='big', signed=True)
    return adc_value

try:
    # Example: Configure the ADC (refer to datasheet for actual configuration)
    # This is a placeholder; you would need to send specific configuration bytes
    # to the ADC_CONTROL register, setup channels, etc.
    #write_register(REG_ADC_CONTROL, [0x01, 0x02]) 

#
#    #       Cont. read
#    value1 = ( 1 << 3 )
#
#    #        POWER_MODE 11=full power
#    value2 = ( 3 << 6 )
#
#    write_register(REG_ADC_CONTROL, [0, 0]) 

    REG_STATUS      =  0x00
    REG_ADC_CONTROL = 0x01
    REG_DATA        = 0x02
    REG_ID          = 0x05
    REG_ERROR       = 0x06
    REG_CHANNEL     = 0x09

    k = 0
    while True:
        print ( "STATUS register:", read_register( REG_STATUS     , 1 ) )
        print ( "ADC_CONTROL reg:", read_register( REG_ADC_CONTROL, 2 ) )
        print ( "DATA        reg:", read_register( REG_DATA       , 3 ) )
        print ( "ID    register:",  read_register( REG_ID         , 1 ) )
        print ( "ERROR register:",  read_register( REG_ERROR      , 3 ) )
        print ( "CHANNEL register:",read_register( REG_CHANNEL    , 2 ) )
        print ()

        time.sleep(2) # Read every 500ms
        k = (k+1)%10

except KeyboardInterrupt:
    print("Exiting...")

finally:
    spi.close()
