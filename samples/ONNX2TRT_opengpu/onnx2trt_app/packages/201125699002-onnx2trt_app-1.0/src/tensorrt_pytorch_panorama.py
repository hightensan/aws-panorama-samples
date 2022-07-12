import os
os.environ["PYTHON_EGG_CACHE"] = "/panorama/.cache"

import boto3
s3 = boto3.resource('s3')

import panoramasdk as p
import os
import sys
import numpy as np
from yolov5trt import YoLov5TRT

import logging
from logging.handlers import RotatingFileHandler
import utils
log = logging.getLogger('my_logger')
log.setLevel(logging.DEBUG)
handler = RotatingFileHandler("/opt/aws/panorama/logs/app.log", maxBytes=10000000, backupCount=2)
formatter = logging.Formatter(fmt='%(asctime)s %(levelname)-8s %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
log.addHandler(handler)

categories = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
            "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
            "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
            "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
            "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
            "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
            "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
            "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
            "hair drier", "toothbrush"]

HUMAN_CLASS  = categories.index("person")

class ObjectDetectionApp(p.node):

    def __init__(self):
        self.model_batch_size = self.inputs.batch_size.get()
        self.pre_processing_output_size = 640
        self.onnx_file_path = "/panorama/yolov5s.onnx"
        self.engine_file_path = "/opt/aws/panorama/storage/yolov5s_dynamic_148.engine"
        self.fp = 16
        self.engine_batch_size = "1 4 8"
        self.is_dynamic = True
        # The reason we use os system here instead of using function call is to save memory.
        # Building engines will runtime load more tensorrt library, and cuase more memory usage.
        # And the loaded library will be released only after the app ends.
        # Thus here using a system call to trigger a standalone process can solve the problem. 
        # (The process will die after building engine file, and thus release loaded library)
        # Another possible way is using Python inbuilt Process. However, Process under Panorama cannot access GPU.
        if not os.path.exists(self.engine_file_path):
            os.system("python3 /opt/aws/panorama/storage/onnx2trt/onnx_tensorrt.py -i {} -o {} -p {} -b {}".format(
                self.onnx_file_path, self.engine_file_path, self.fp, self.engine_batch_size
            ))
        
        self.yolov5_wrapper = YoLov5TRT(self.engine_file_path, self.model_batch_size, self.is_dynamic)
    
    def get_frames(self):
        input_frames = self.inputs.video_in.get()
        return input_frames


    def run(self):
        input_images = list()
        # TODO: supprot batch_size > 1, with multiple
        image_list = [] # An image queue
        while True:
            try:
                input_frames = self.get_frames()
                input_images = [frame.image for frame in input_frames]
                image_list+=input_images
                if len(image_list) >= self.model_batch_size:
                    image_raw_list = image_list[:self.model_batch_size]
                    input_image_batch = self.yolov5_wrapper.preprocess_image_batch(image_raw_list)
                    output_batch = self.yolov5_wrapper.infer(input_image_batch)
                    prediction = self.yolov5_wrapper.post_process_batch(
                        output_batch, input_image_batch[0], image_raw_list[0],
                        filtered_classes=[HUMAN_CLASS]
                    )

                    # Draw rectangles and labels on the original image
                    for image_idx, det_results in enumerate(prediction):
                        for box_idx, bbox in enumerate(det_results):
                            bbox = bbox.tolist()
                            coord = bbox[:4]
                            score = bbox[4]
                            class_id = bbox[5]
                            utils.plot_one_box(coord, image_raw_list[image_idx],
                                label="{}:{:.2f}".format(categories[int(class_id)], score))

                    image_list = image_list[self.model_batch_size:]
                self.outputs.video_out.put(input_frames)
        
            except Exception as e:
                self.yolov5_wrapper.destroy()
                log.exception('Exception is {}'.format(e))
                pass


if __name__ == '__main__':
    try:
        app = ObjectDetectionApp()
        app.run()
    except Exception as err:
        log.exception('App Did not Start {}'.format(err))
        sys.exit(1)
