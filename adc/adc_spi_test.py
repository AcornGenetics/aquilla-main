import spidev
import time

# --- AD7124-8 specific definitions ---
# The ID register is at address 0x05.
# To read a register, the command byte is 01xxxxxx, where xxxxxx is the register address.
# 0x45 = 0b01000101 (read command for register 0x05)
AD7124_READ_ID_REGISTER_COMMAND = 0x45

# The AD7124 is a 24-bit ADC, but its registers are 8-bit. The ID register is a single byte.
# We need to send an extra dummy byte to clock in the data we want to read.
DUMMY_BYTE = 0x00

# --- SPI device configuration ---
# Adjust these based on your Raspberry Pi and wiring.
# bus = 0 for /dev/spidev0.x
# device = 0 for /dev/spidev0.0 (CS0)
spi_bus = 0
spi_device = 0 

# Create and configure the SPI object
spi = spidev.SpiDev()
try:
    spi.open(spi_bus, spi_device)
    print(f"Opened /dev/spidev{spi_bus}.{spi_device}")
    
    # Set SPI mode and speed according to the AD7124 datasheet
    spi.mode = 0b11 # CPOL=1, CPHA=1 for the AD7124
    spi.max_speed_hz = 1000 # Start with a moderate speed, e.g., 1MHz

    # Perform the SPI transfer.
    # The xfer2() function sends a list of bytes and returns a list of received bytes.
    # The first byte is the command; the second is the dummy byte to trigger the response.
    #
    print("Attempting to read ID register (0x05)...")
    tx_buffer = [AD7124_READ_ID_REGISTER_COMMAND, DUMMY_BYTE]
    rx_buffer = spi.xfer2(tx_buffer)
    
    # The ID value is the second byte received (at index 1)
    device_id = rx_buffer[1]
    
    # The expected ID value depends on the revision, but will be non-zero.
    # A read of 0x00 is a strong indicator of a communication failure.
    if device_id != 0x00:
        print(f"\nCommunication successful! Device ID: {hex(device_id)}")
    else:
        print("\nCommunication failed. Received 0x00. Check wiring and power.")
        
except spidev.SpiDevIOError as e:
    print(f"SPI I/O Error: {e}")
    print("Ensure SPI is enabled and the correct bus/device are specified.")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
finally:
    # Always close the SPI connection
    if spi:
        spi.close()
        print("\nSPI connection closed.")

