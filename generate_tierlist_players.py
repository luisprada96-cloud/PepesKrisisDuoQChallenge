"""Build the participant name tiles with the existing tierlist visual style.

Development utility: requires Pillow and a bold TrueType font, never runs on the server.
Example: python generate_tierlist_players.py --font C:/Windows/Fonts/arialbd.ttf
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from tierlists_service import PLAYER_ITEMS


def background():
    # The same dark teal-to-purple palette and centered white name as the team tiles.
    stops = [(0, (6, 22, 30)), (.25, (8, 17, 28)), (.5, (7, 10, 18)),
             (.75, (16, 10, 24)), (1, (16, 9, 22))]
    image = Image.new('RGB', (400, 400))
    pixels = image.load()
    for y in range(400):
        for x in range(400):
            position = (x + y) / 798
            left, right = next((a, b) for a, b in zip(stops, stops[1:]) if position <= b[0])
            weight = (position - left[0]) / (right[0] - left[0])
            pixels[x, y] = tuple(round(a + (b-a)*weight) for a, b in zip(left[1], right[1]))
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent/'assets'/'tierlist')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = background().resize((1600, 1600), Image.Resampling.BICUBIC)
    for item in PLAYER_ITEMS:
        image = base.copy()
        draw = ImageDraw.Draw(image)
        size = 60 * 4
        while True:
            font = ImageFont.truetype(str(args.font), size)
            if draw.textlength(item['name'], font=font) <= 352*4 or size <= 28*4:
                break
            size -= 4
        bbox = draw.textbbox((0, 0), item['name'], font=font)
        xy = ((1600-(bbox[2]-bbox[0]))/2-bbox[0], (1600-(bbox[3]-bbox[1]))/2-bbox[1])
        draw.text(xy, item['name'], font=font, fill=(240, 244, 251))
        image.resize((400, 400), Image.Resampling.LANCZOS).save(args.output/Path(item['image']).name, optimize=True)
    print(f"Generated {len(PLAYER_ITEMS)} participant tiles (400 x 400).")


if __name__ == '__main__':
    main()
