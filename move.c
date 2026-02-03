#include <gpiod.h>
#include <stdio.h>
#include <unistd.h> // For sleep()

#ifndef	CONSUMER
#define	CONSUMER "gpio-toggle"
#endif

int main(int argc, char **argv)
{
	char *chipname = "gpiochip0"; // Or "gpiochip4" for Raspberry Pi 5
	unsigned int line_offset = 17; // Example: GPIO17 (BCM numbering)
	struct gpiod_chip *chip;
	struct gpiod_line *line;
	int i, ret;

	// Open the GPIO chip
	chip = gpiod_chip_open_by_name(chipname);
	if (!chip) {
		perror("gpiod_chip_open_by_name");
		return 1;
	}

	// Get the GPIO line
	line = gpiod_chip_get_line(chip, line_offset);
	if (!line) {
		perror("gpiod_chip_get_line");
		gpiod_chip_close(chip);
		return 1;
	}

	// Request the line as an output
	ret = gpiod_line_request_output(line, CONSUMER, 0); // Initial state LOW
	if (ret < 0) {
		perror("gpiod_line_request_output");
		gpiod_chip_close(chip);
		return 1;
	}

	// Toggle the GPIO pin 5 times
	for (i = 0; i < 5; i++) {
		ret = gpiod_line_set_value(line, 1); // Set HIGH
		if (ret < 0) {
			perror("gpiod_line_set_value");
			break;
		}
		printf("GPIO %d HIGH\n", line_offset);
		sleep(1); // Wait for 1 second

		ret = gpiod_line_set_value(line, 0); // Set LOW
		if (ret < 0) {
			perror("gpiod_line_set_value");
			break;
		}
		printf("GPIO %d LOW\n", line_offset);
		sleep(1); // Wait for 1 second
	}

	// Release the GPIO line and close the chip
	gpiod_line_release(line);
	gpiod_chip_close(chip);

	return ret < 0 ? 1 : 0;
}
