from pathlib import Path
from matplotlib.image import imread, imsave
import random


def rgb2gray(rgb):
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    gray = 0.2989 * r + 0.5870 * g + 0.1140 * b
    return gray


class Img:

    def __init__(self, path):
        """
        Do not change the constructor implementation
        """
        self.path = Path(path)
        self.data = rgb2gray(imread(path)).tolist()

    def save_img(self):
        """
        Do not change the below implementation
        """
        new_path = self.path.with_name(self.path.stem + '_filtered' + self.path.suffix)
        imsave(new_path, self.data, cmap='gray')
        return new_path

    def blur(self, blur_level=16):

        height = len(self.data)
        width = len(self.data[0])
        filter_sum = blur_level ** 2

        result = []
        for i in range(height - blur_level + 1):
            row_result = []
            for j in range(width - blur_level + 1):
                sub_matrix = [row[j:j + blur_level] for row in self.data[i:i + blur_level]]
                average = sum(sum(sub_row) for sub_row in sub_matrix) // filter_sum
                row_result.append(average)
            result.append(row_result)

        self.data = result

    def contour(self):
        for i, row in enumerate(self.data):
            res = []
            for j in range(1, len(row)):
                res.append(abs(row[j-1] - row[j]))

            self.data[i] = res

    def rotate(self):
        """
        Rotate the image 90 degrees clockwise.
        """
        #number of rows in the image matrix
        height = len(self.data)
        #number of columns in the image matrix
        width = len(self.data[0])
        # Create a new matrix with swapped dimensions(height and width)
        rotated = [[0] * height for _ in range(width)]

        for i in range(height):
            for j in range(width):
                # Assign value to new rotated position
                rotated[j][height - 1 - i] = self.data[i][j]

        self.data = rotated

    def salt_n_pepper(self):
        """
        randomly set pixels to 0 (black) or 255 (white).
        """
        for i in range(len(self.data)):
            for j in range(len(self.data[0])):
                rand = random.random()
                if rand < 0.2:
                    self.data[i][j] = 255  # Salt (white)
                elif rand > 0.8:
                    self.data[i][j] = 0  # Pepper (black)

    def concat(self, other_img, direction='horizontal'):
        """
        Concatenate this image with another image either horizontally or vertically.
        """
        if direction == 'horizontal':
            if len(self.data) != len(other_img.data):
                raise ValueError("Images must have the same height for horizontal concatenation.")
            # Merge rows side by side
            self.data = [row1 + row2 for row1, row2 in zip(self.data, other_img.data)]

        elif direction == 'vertical':
            if len(self.data[0]) != len(other_img.data[0]):
                raise ValueError("Images must have the same width for vertical concatenation.")
            # Stack rows on top of each other
            self.data = self.data + other_img.data

        else:
            raise ValueError("Direction must be 'horizontal' or 'vertical'.")

    def segment(self):
        """
        Segment the image into binary black.
        pixels with an intensity greater than 100 are replaced with a white pixel(255)
        else black pixel(0)
        """
        for i in range(len(self.data)):
            for j in range(len(self.data[0])):
                self.data[i][j] = 255 if self.data[i][j] > 100 else 0
