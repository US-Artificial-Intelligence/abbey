import ocrmypdf
import requests
import time
from ..configs.secrets import MATHPIX_API_KEY, MATHPIX_API_APP
from multiprocessing import Process
from ..utils import remove_ext
import json
import os

# NOTE: "OCR_PROVIDERS" variable at the bottom of the file

MATHPIX_OCR_MAX_WAIT = 10 * 60  # max wait time for mathpix OCR in seconds - remember though this uses exponetial fallback (see retriever.py)
MATHPIX_OCR_MAX_ATTEMPTS = 2  # Max number of times to retry OCR in failure
LOCAL_OCR_TIMEOUT = 20 * 60 #  The timeout for local optical character recognition, in seconds

class OCR():
    def __init__(self, code, accept_formats) -> None:
        self.code = code  # unique, descriptive string associated with the model e.g., "mathpix" or "local"
        self.accept_formats = accept_formats  # the formats that do_ocr can accept e.g. ["pdf", "png"]

    # Returns path of new file that has readable text
    # Will raise an error if the OCR fails
    def do_ocr(self, ext, src_name) -> str:
        pass


# Does OCR using a local instance of ocrmypdf, which is based on Tesseract
# May require additional setup and installations to run properly!
class LocalOCR(OCR):
    def __init__(self) -> None:
        super().__init__(
            code='local',
            accept_formats=['pdf']
        )

    def do_ocr(self, ext, src_name):
        assert(ext == 'pdf')
        # break off into separate process and wait.
        def ocr_process(src_name):
            ocrmypdf.configure_logging(-1)
            ocrmypdf.ocr(src_name, src_name, deskew=True, force_ocr=True, progress_bar=False)
        
        p = Process(target=ocr_process, args=(src_name,))
        p.daemon = True  # ensure it stops after server exits.
        p.start()
        p.join(timeout=LOCAL_OCR_TIMEOUT)

        if p.is_alive():
            p.terminate()
            raise Exception("Local OCR process timed out")

        return src_name


class MathpixOCR(OCR):
    def __init__(self) -> None:
        self.img_formats = ["png", "jpeg", "jpg", "jpe", "bmp", "dib", "jp2", "webp", "pbm", "pgm", "ppm", "pxm", ".pnm", "pfm", "sr", "ras", "tiff", "tif", "exr", "hdr", "pic"]
        super().__init__(
            code='mathpix',
            accept_formats = ["pdf", *self.img_formats]
        )


    def do_ocr(self, ext, src_name):
        if ext == 'pdf':
            return self._do_ocr_pdf(src_name)
        elif ext in self.img_formats:
            return self._do_ocr_image(src_name)
        else:
            raise Exception(f"Mathpix OCR does not work on file with extension '{ext}'.")


    def _do_ocr_pdf(self, src_name):
         # API: https://docs.mathpix.com/?shell#response-body-5
        headers = {
            'app_id': MATHPIX_API_APP,
            'app_key': MATHPIX_API_KEY
        }

        files = {
            'file': (src_name, open(src_name, 'rb')),
        }

        # Think about what formats you want...
        # This does markdown.
        
        desired_ext = ".abbeyjson"
        outname = remove_ext(src_name) + desired_ext
        data = {
            'options_json': json.dumps({
                'conversion_formats': {
                    'md': True,
                    'docx': False,
                    'tex.zip': False,
                    'html': False
                }
            })
        }

        init_attempts = 0
        while True:
            if init_attempts >= MATHPIX_OCR_MAX_ATTEMPTS - 1:
                raise Exception("Initial Mathpix OCR request max attempts exceeded.")

            response = requests.post(
                'https://api.mathpix.com/v3/pdf',
                headers=headers,
                files=files,
                data=data
            )

            if response.status_code == 200:
                my_json = response.json()
                pdf_id = my_json['pdf_id']
                tries = 0
                # Exponential decay
                while True:
                    
                    to_wait = 1.5**tries
                    if to_wait > MATHPIX_OCR_MAX_WAIT:
                        raise Exception("Mathpix got job, but processing exceeded max wait.")
                    time.sleep(to_wait)
                    
                    response = requests.get(
                        'https://api.mathpix.com/v3/pdf/' + str(pdf_id),
                        headers=headers
                    )

                    if response.status_code == 200:
                        my_json = response.json()

                        if my_json['status'] == 'completed':

                            response = requests.get(
                                'https://api.mathpix.com/v3/pdf/'+str(pdf_id)+'.lines.json', # desired_ext
                                headers=headers
                            )
                            
                            if response.status_code == 200:
                                my_json = response.json()
                                structured_data = {'pages': []}
                                for page in my_json['pages']:
                                    page_data = {'lines': []}
                                    for line in page['lines']:
                                        page_data['lines'].append(line['text'])
                                    structured_data['pages'].append(page_data)
                                
                                with open(outname, 'w') as f:
                                    json.dump(structured_data, f)

                                if outname != src_name:
                                    os.remove(src_name)
                                return outname
                            else:
                                raise Exception("Mathpix said it was completed, but fetching the file failed.")

                    tries += 1
                
            time.sleep(1)
            init_attempts += 1


    def _do_ocr_image(self, src_name):
        # API: https://docs.mathpix.com/?shell#response-body-5
        headers = {
            'app_id': MATHPIX_API_APP,
            'app_key': MATHPIX_API_KEY
        }

        files = {
            'file': (src_name, open(src_name, 'rb')),
        }

        # Think about what formats you want...
        # This does markdown.
        
        desired_ext = ".txt"
        outname = remove_ext(src_name) + desired_ext
        data = {
            'options_json': json.dumps({
                'math_inline_delimiters': ["$", "$"],
                'rm_spaces': False
            })
        }
        
        response = requests.post(
            'https://api.mathpix.com/v3/text',
            headers=headers,
            files=files,
            data=data
        )

        if response.status_code == 200:
            my_json = response.json()
            txt = my_json['text']
            with open(outname, 'w') as f:
                f.write(txt)
            
            if outname != src_name:
                os.remove(src_name)
            
            return outname
        
        raise Exception("Mathpix image api didn't return 200")


class DisabledOCR(OCR):
    def __init__(self) -> None:
        super().__init__(
            code='disabled',
            accept_formats = []
        )

    def do_ocr(self, ext, src_name):
        return src_name


OCR_PROVIDERS = {
    'local': LocalOCR(),
    'mathpix': MathpixOCR(),
    'disabled': DisabledOCR()
}
