import spidev
import time

# SPI bus and device (CS) number
spi_bus = 0
spi_cs = 0

# Open the SPI bus
spi = spidev.SpiDev()
spi.open(spi_bus, spi_cs)

# Configure SPI settings
spi.max_speed_hz = 1000000  # Set maximum clock speed (e.g., 1 MHz)
spi.mode = 1                # Set SPI mode (CPOL=0, CPHA=1 for ADS7124)

# ADS7124 Register Addresses (from datasheet)
REG_STATUS = 0x00
REG_DATA = 0x02
REG_CONFIG = 0x04

# Function to read from a register
def read_register(reg_address, num_bytes):
    # ADS7124 read command: 0x5X, where X is the register address
    command_byte = 0x50 | (reg_address >> 3)
    
    # Perform the SPI transaction: send command, receive data
    rx_data = spi.xfer2([command_byte] + [0] * num_bytes)
    
    return rx_data[1:]

# Function to write to a register
def write_register(reg_address, data_bytes):
    # ADS7124 write command: 0x1X, where X is the register address
    command_byte = 0x10 | (reg_address >> 3)
    
    # Perform the SPI transaction: send command and data
    spi.xfer2([command_byte] + data_bytes)

try:
    # Example: Write to the config register to set a channel and start conversion
    # Consult the datasheet for the correct bit values
    # For example, to enable continuous conversion mode
    write_register(REG_CONFIG, [0x01])

    for i in range ( 10 ):
        print ( read_register ( i, 1 ) )
    
    while True:
        # Read the raw 24-bit (3-byte) data
        raw_data_bytes = read_register(REG_DATA, 3)
        
        # Combine the bytes into a single integer
        raw_reading = (raw_data_bytes[0] << 16) | (raw_data_bytes[1] << 8) | raw_data_bytes[2]
        
        # Print the raw reading
        print(f"Raw Reading: {raw_reading}")
        
        time.sleep(1)

except KeyboardInterrupt:
    print("Exiting...")
finally:
    spi.close()

