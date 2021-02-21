#! /usr/bin/env python
import collections
import contextlib
import copy
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.append('/usr/share/inkscape/extensions')
import inkex
inkex.localization.localize()

Layer = collections.namedtuple('Layer', ['id', 'label', 'tag'])
Export = collections.namedtuple('Export', ['visible_layers', 'file_name'])

FIXED = '[fixed]'
EXPORT = '[export]'

PNG = 'png'
SVG = 'svg'
JPEG = 'jpeg'


class LayerExport(inkex.Effect):
    def __init__(self):
        inkex.Effect.__init__(self)
        self.arg_parser.add_argument('-o', '--output-dir',
                                     action='store',
                                     type=str,
                                     dest='output_dir',
                                     default='~/',
                                     help='Path to an output directory')
        self.arg_parser.add_argument('-f', '--file-type',
                                     action='store',
                                     choices=(PNG, SVG, JPEG),
                                     dest='file_type',
                                     default='png',
                                     help='Exported file type')
        self.arg_parser.add_argument('--fit-contents',
                                     action='store',
                                     type=str,
                                     dest='fit_contents',
                                     default=False,
                                     help='Fit output to content bounds')
        self.arg_parser.add_argument('--dpi',
                                     action='store',
                                     type=int,
                                     dest='dpi',
                                     default=None,
                                     help="Export DPI value")
        self.arg_parser.add_argument('--enumerate',
                                     action='store',
                                     type=str,
                                     dest='enumerate',
                                     default=None,
                                     help="Export DPI value")

    def effect(self):
        
        #process bool inputs that were read as strings
        self.options.fit_contents = True if self.options.fit_contents == 'true' else False
        self.options.enumerate    = True if self.options.enumerate    == 'true' else False

        output_dir = os.path.expanduser(self.options.output_dir)
        if not os.path.exists(os.path.join(output_dir)):
            os.makedirs(os.path.join(output_dir))

        layer_list = self.get_layer_list()
        export_list = self.get_export_list(layer_list)
        with _make_temp_directory() as tmp_dir:
            for export in export_list:
                svg_file = self.export_to_svg(export, tmp_dir)

                if self.options.file_type == PNG:
                    if not self.convert_svg_to_png(svg_file, output_dir):
                        break
                elif self.options.file_type == SVG:
                    if not self.convert_svg_to_svg(svg_file, output_dir):
                        break
                elif self.options.file_type == JPEG:
                    if not self.convert_png_to_jpeg(
                            self.convert_svg_to_png(svg_file, tmp_dir),
                            output_dir):
                        break

    def get_layer_list(self):
        svg_layers = self.document.xpath('//svg:g[@inkscape:groupmode="layer"]',
                                         namespaces=inkex.NSS)
        layer_list = []

        for layer in svg_layers:
            label_attrib_name = '{%s}label' % layer.nsmap['inkscape']
            if label_attrib_name not in layer.attrib:
                continue

            layer_id = layer.attrib['id']
            layer_label = layer.attrib[label_attrib_name]

            if layer_label.lower().startswith(FIXED):
                layer_type = FIXED
                layer_label = layer_label[len(FIXED):].lstrip()
            elif layer_label.lower().startswith(EXPORT):
                layer_type = EXPORT
                layer_label = layer_label[len(EXPORT):].lstrip()
            else:
                continue

            layer_list.append(Layer(layer_id, layer_label, layer_type))

        # Layers are displayed in the reversed order in Inkscape compared to SVG
        return list(reversed(layer_list))

    def get_export_list(self, layer_list):
        export_list = []

        for counter, layer in enumerate(layer_list):
            if layer.tag == FIXED:
                continue

            visible_layers = {
                other_layer.id for other_layer in layer_list
                if other_layer.tag == FIXED or other_layer.id == layer.id
            }

            file_name = layer.label
            if self.options.enumerate:
                file_name = '%03d_%s' % (counter + 1, file_name)

            export_list.append(Export(visible_layers, file_name))

        return export_list

    def export_to_svg(self, export, output_dir):
        """
        Export a current document to an Inkscape SVG file.
        :arg Export export: Export description.
        :arg str output_dir: Path to an output directory.
        :return Output file path.
        """
        document = copy.deepcopy(self.document)

        svg_layers = document.xpath('//svg:g[@inkscape:groupmode="layer"]',
                                    namespaces=inkex.NSS)

        for layer in svg_layers:
            if layer.attrib['id'] in export.visible_layers:
                layer.attrib['style'] = 'display:inline'
            else:
                layer.attrib['style'] = 'display:none'

        output_file = os.path.join(output_dir, export.file_name + '.svg')
        document.write(output_file)

        return output_file

    def convert_svg_to_png(self, svg_file, output_dir):
        """
        Convert an SVG file into a PNG file.
        :param str svg_file: Path an input SVG file.
        :param str output_dir: Path to an output directory.
        :return Output file path.
        """
        file_name = os.path.splitext(os.path.basename(svg_file))[0]
        output_file = os.path.join(output_dir, file_name + '.png')
        command = [
            'inkscape',
            svg_file.encode('utf-8'),
            '--batch-process', 
            '--export-area-drawing' if self.options.fit_contents else 
            '--export-area-page',
            '--export-dpi', str(self.options.dpi),
            '--export-type', 'png',
            '--export-filename', output_file.encode('utf-8'),
        ]
        result = subprocess.run(command, capture_output=True)
        if result.returncode != 0:
            raise Exception('Failed to convert %s to PNG' % svg_file)

        return output_file

    def convert_svg_to_svg(self, svg_file, output_dir):
        """
        Convert an [Inkscape] SVG file into a standard (plain) SVG file.
        :param str svg_file: Path an input SVG file.
        :param str output_dir: Path to an output directory.
        :return Output file path.
        """
        file_name = os.path.splitext(os.path.basename(svg_file))[0]
        output_file = os.path.join(output_dir, file_name + '.svg')
        command = [
            'inkscape',
            svg_file.encode('utf-8'),    
            '--batch-process', 
            '--export-area-drawing' if self.options.fit_contents else 
            '--export-area-page',
            '--export-dpi', str(self.options.dpi),
            '--export-plain-svg', 
            '--vacuum-defs',
            '--export-filename',output_file.encode('utf-8')
        ]
        result = subprocess.run(command, capture_output=True)
        if result.returncode != 0:
            raise Exception('Failed to convert %s to SVG' % svg_file)

        return output_file

    @staticmethod
    def convert_png_to_jpeg(png_file, output_dir):
        """
        Convert a PNG file into a JPEG file.
        :param str png_file: Path an input PNG file.
        :param str output_dir: Path to an output directory.
        :return Output file path.
        """
        if png_file is None:
            return None

        file_name = os.path.splitext(os.path.basename(png_file))[0]
        output_file = os.path.join(output_dir, file_name + '.jpeg')
        command = ['convert', png_file, output_file]
        result = subprocess.run(command, capture_output=True)
        if result.returncode != 0:
            raise Exception('Is ImageMagick installed?\n'
                            'Failed to convert %s to JPEG' % png_file)

        return output_file


@contextlib.contextmanager
def _make_temp_directory():
    temp_dir = tempfile.mkdtemp(prefix='tmp-inkscape')
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir)


if __name__ == '__main__':
    try:
        LayerExport().run(output=False)
    except Exception as e:
        inkex.errormsg(str(e))
        sys.exit(1)
