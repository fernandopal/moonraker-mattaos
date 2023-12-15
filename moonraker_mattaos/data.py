import time
import threading
import requests
import csv
import json
from .utils import (
    clean_gcode_list,
    find_last_gcode_line_num,
    get_api_url,
    get_gcode_upload_dir,
    make_timestamp,
    generate_auth_headers,
    SAMPLING_TIMEOUT,
    MATTA_TMP_DATA_DIR,
)
import os
import shutil
from PIL import Image
import io


class DataEngine:
    def __init__(self, logger, logger_cmd, settings, matta_printer):
        self._printer = matta_printer
        self._settings = settings
        self._logger = logger
        self._logger_cmd = logger_cmd
        self.image_count = 0
        self.gcode_path = None
        self.csv_print_log = None
        self.csv_writer = None
        self.csv_path = None
        self.upload_attempts = 0


        # -------------------------- Debug Area --------------------------

        # PRINTER TESTSSSSSSS
        if False:
            try:
                self._logger.info(self._printer.get_printer_state_object())
                time.sleep(.5)
                self._logger.info(self._printer.get_printer_temp_object())
                time.sleep(.5)
                self._logger.info(self._printer.get_print_stats_object())
                time.sleep(.5)
                self._logger.info(self._printer.get_gcode_base_name())
                time.sleep(.5)
            except Exception as e:
                self._logger.error(e)

        # self._logger.info(self._printer.get_gcode_base_name())

        # self._logger.info(self._printer.make_job_name())

        # data_path = os.path.join(MATTA_TMP_DATA_DIR, self._printer.make_job_name())
        # os.makedirs(data_path)
        # self._logger.debug(f"Successfully created job directory at {data_path}")

        # -----------------------------------------------------------------

        self._logger.info("Starting data thread")
        self.start_data_thread()

        # # # Temp loop to trap service and make it continue running
        # while True:
        #     self._logger.info("Temp loop service trap in Data loop thread")
        #     time.sleep(60)
        #     pass

        

    def start_data_thread(self):
        """
        Start the main combined thread for capturing both CSV and images
        """
        self._logger.debug("Setting up main data thread...")
        self.main_data_thread = threading.Thread(target=self.data_thread_loop)
        self.main_data_thread.daemon = True
        self.main_data_thread.start()
        self._logger.debug("Main data thread running.")

    def get_job_dir(self, with_data_dir=True):
        """Gets the directory for the current print job."""
        if self._printer.current_job is not None:
            job_name = self._printer.current_job.replace(":", "-")
            if with_data_dir:
                return os.path.join(MATTA_TMP_DATA_DIR, job_name)
            return job_name
        else:
            return None

    def create_job_dir(self):
        """
        Creates the directory for the current print job.
        Returns the path of the created directory.
        """
        data_path = self.get_job_dir()
        try:
            os.makedirs(data_path)
            self._logger.debug(f"Successfully created job directory at {data_path}")
        except OSError as e:
            self._logger.error(
                f"Failed to create directory - OS Error ({e.errno}): {e.strerror}, Directory: {data_path}"
            )
            self._logger.error(f"Current directory: {os.getcwd()}")
        return data_path

    def reset_job_data(self):
        """
        Reset the job-related data after a print job.
        """
        self.csv_print_log = None
        self.csv_writer = None
        try:
            shutil.rmtree(self.get_job_dir())
        except OSError as e:
            pass
        except TypeError as e:
            pass
        self.csv_path = None
        self._printer.new_print_job = True
        self._printer.current_job = None
        self.gcode_path = None
        self.image_count = 0
        self._printer.gcode_line_num_no_comments = None
        self._printer.gcode_cmd = None

    def get_gcode_data(self):
        """
        Gets the gcode data from the printer.
        """
        gcode_raw_list = self._printer.get_gcode_store()
        gcode_list = clean_gcode_list(gcode_raw_list)
        gcode_line_num = find_last_gcode_line_num(gcode_list)
        last_gcode = gcode_list[-1]
        response =  {
            "gcode_line_num": gcode_line_num,
            "gcode_cmd": last_gcode["message"],
        }
        self._logger.debug(f"Gcode data: {response}")
        return response

    def create_metadata(self):
        temps = self._printer.get_printer_temp_object()
        printer_objects = self._printer.get_printer_objects()
        # gcode_data = self.get_gcode_data()
        metadata = {
            "count": self.image_count,
            "timestamp": make_timestamp(),            
            "flow_rate": printer_objects["flow_rate"] * 100,
            "feed_rate": printer_objects["feed_rate"] * 100,
            "z_offset": printer_objects["z_offset"],
            "hotend_target": temps["tool0"]["target"],
            "hotend_actual": temps["tool0"]["actual"],
            "bed_target": temps["bed"]["target"],
            "bed_actual": temps["bed"]["actual"],
            # "gcode_line_num": gcode_data["gcode_line_num"],
            # "gcode_cmd": gcode_data["gcode_cmd"],
            "nozzle_tip_coords_x": int(self._settings["nozzle_tip_coords_x"]),
            "nozzle_tip_coords_y": int(self._settings["nozzle_tip_coords_y"]),
            "flip_h": self._settings["flip_h"],
            "flip_v": self._settings["flip_v"],
            "rotate": self._settings["rotate"],
        }
        return metadata

    def gcode_upload(self, job_name, gcode_path):
        """
        Uploads G-code files to the specified base URL.

        Args:
            files (dict): A dictionary containing the files to upload.
            headers (dict): Additional headers to include in the request.

        Raises:
            requests.exceptions.RequestException: If an error occurs during the upload.
        """
        self._logger.debug("Posting gcode")
        with open(gcode_path, "rb") as gcode:
            gcode_name = os.path.basename(gcode_path) # ? Check if it needs that, since we're just getting the filename
            metadata = {
                "name": os.path.splitext(gcode_name)[0],
                "long_name": job_name,
                "gcode_file": gcode_name,
                "start_time": make_timestamp(),
            }
            data = {"data": json.dumps(metadata)}
            files = {
                "gcode_obj": (job_name, gcode, "text/plain"),
            }
            full_url = get_api_url() + "print-jobs/remote/start-job"
            headers = generate_auth_headers(self._settings["auth_token"])
            try:
                resp = requests.post(
                    url=full_url, data=data, files=files, headers=headers
                )
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                self._logger.error(e)

    def image_upload(self, image):
        """
        Uploads image files to the specified base URL.

        Args:
            files (dict): A dictionary containing the files to upload.
            headers (dict): Additional headers to include in the request.

        Raises:
            requests.exceptions.RequestException: If an error occurs during the upload.
        """
        self._logger.debug("Posting image")
        image_name = f"image_{self.image_count}.png"

        # Load the image using PIL
        pil_image = Image.open(io.BytesIO(image))

        # Flip the image if necessary
        if self._settings["flip_h"]:
            pil_image = pil_image.transpose(Image.FLIP_LEFT_RIGHT)
        if self._settings["flip_v"]:
            pil_image = pil_image.transpose(Image.FLIP_TOP_BOTTOM)
        if self._settings["rotate"]:
            pil_image = pil_image.transpose(Image.ROTATE_90)

        self._logger.debug("Image transforms complete")
        # Convert the PIL image back to bytes
        byte_arr = io.BytesIO()
        pil_image.save(byte_arr, format="PNG")
        image = byte_arr.getvalue()

        self._logger.debug("Image loaded")
        metadata = {
            "name": image_name,
            "img_file": image_name,
        }
        metadata.update(self.create_metadata())
        data = {"data": json.dumps(metadata)}
        files = {
            "image_obj": (image_name, image, "image/png"),
        }
        full_url = get_api_url() + "images/print/predict/new-image"
        headers = generate_auth_headers(self._settings["auth_token"])
        try:
            resp = requests.post(
                url=full_url, data=data, files=files, headers=headers, timeout=5,
            )
            self._logger.debug("Image posted")
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            self._logger.info(e)

    def finished_upload(self, job_name, gcode_path, csv_path):
        """
        Notifies the server that the print job has finished.

        Args:
            job_name (str): The name of the print job.

        Raises:
            requests.exceptions.RequestException: If an error occurs during the upload.
        """
        self._logger.debug(csv_path)
        with open(csv_path, "rb") as csv:
            gcode_name = os.path.basename(gcode_path)
            csv_name = os.path.basename(csv_path)
            self._logger.debug(gcode_name)
            self._logger.debug(csv_name)
            metadata = {
                "name": os.path.splitext(gcode_name)[0],
                "long_name": job_name,
                "csv_file": csv_name,
                "end_time": make_timestamp(),
            }
            data = {"data": json.dumps(metadata)}
            files = {
                "csv_obj": (csv_name, csv, "text/csv"),
            }
            self._logger.debug(json.dumps(data))
            full_url = get_api_url() + "print-jobs/remote/end-job"
            self._logger.debug(full_url)
            headers = generate_auth_headers(self._settings["auth_token"])
            self._logger.debug(headers)
            try:
                resp = requests.post(
                    url=full_url, data=data, files=files, headers=headers
                )
                resp.raise_for_status()
                self._logger.debug("Posting finished")
                self._logger.debug(resp)
            except requests.exceptions.RequestException as e:
                self._logger.error(e)

    def is_new_job(self):
        """
        Checks if a new print job has started and performs necessary setup tasks.

        Returns:
            bool: True if a new job has started, False otherwise.
        """

        try:
            state = self._printer.get_printer_state_object()
            state = state['text']
            if state == 'Error':
                self._logger.debug("Error temporarily classified as operational")
        except Exception as e:
            self._logger.error(f"Error getting state object: {e}")


        # TODO remove try except big block later
        try:
            if self._printer.has_job():
                if self._printer.new_print_job:
                    self._logger.debug("New job.")
                    self._printer.new_print_job = False
                    self._printer.current_job = self._printer.make_job_name()
                    self._logger.debug(f"New job: {self._printer.current_job}")
                    try:
                        self.setup_print_log()
                        self.gcode_upload(self._printer.current_job, self.gcode_path)
                    except Exception as e:
                        self._logger.error(
                            f"Failed to set up data collection for print job: {e}"
                        )
                return True

            elif self._printer.is_operational():
                if self._printer.just_finished():
                    self._logger.debug("Just finished a print job.")
                    try:
                        self.cleanup_print_log()
                        self._logger.debug("Print log cleaned up.")
                        self.finished_upload(
                            self._printer.current_job, self.gcode_path, self.csv_path
                        )
                        self._logger.debug("Posted!")
                        self.finished = True
                        self._printer.finished = True
                    except Exception as e:
                        self._logger.error(f"Failed to finish print job: {e}")
                        self.upload_attempts += 1
                        if self.upload_attempts > 3:
                            self.reset_job_data()
                            self.upload_attempts = 0
                            self.finished = True
                            self._printer.finished = True
                self.reset_job_data()
        except Exception as e:
            self._logger.error(f"Error running is_new_job: {e}")

        return False

    def setup_print_log(self):
        """
        Set up the print log file and start the image thread.
        """
        job_dir = self.create_job_dir()
        self.csv_path = os.path.join(job_dir, "print_log.csv")
        self.gcode_path = os.path.join(
            get_gcode_upload_dir(),
            self._printer.get_gcode_base_name(),
        )
        self._logger.debug("G-code file copied.")
        try:
            self.csv_print_log = open(self.csv_path, "w")
            self.csv_writer = csv.writer(self.csv_print_log, delimiter=",")
            self.csv_writer.writerow(self.csv_headers())
            self.csv_print_log.flush()
        except IOError as e:
            self._logger.error(f"Failed to open print log file: {e}")
            self.csv_print_log = None
            self.csv_writer = None

    def cleanup_print_log(self):
        """
        Clean up the print log file and image thread after the print has finished.
        """
        try:
            self.csv_print_log.flush()
            self.csv_print_log.close()
        except AttributeError:
            self._logger.error("CSV print log was never made...")
        except Exception as e:
            self._logger.error(f"Failed to close print log file: {e}")

    def csv_headers(self):
        """Returns a list of CSV headers used for data collection."""
        return [
            "count",
            "timestamp",
            "flow_rate",
            "feed_rate",
            "z_offset",
            "target_hotend",
            "hotend",
            "target_bed",
            "bed",
            # "gcode_line_num_no_comments",
            # "gcode_cmd",
            "nozzle_tip_coords_x",
            "nozzle_tip_coords_y",
            "flip_h",
            "flip_v",
            "rotate",
        ]

    def csv_data_row(self):
        """Fetches data and returns a list for populating a row of a CSV."""
        temps = self._printer.get_printer_temp_object()
        printer_objects = self._printer.get_printer_objects()
        row = [
            self.image_count,
            make_timestamp(),
            printer_objects["flow_rate"] * 100,
            printer_objects["feed_rate"] * 100,
            printer_objects["z_offset"],
            temps["tool0"]["target"],
            temps["tool0"]["actual"],
            temps["bed"]["target"],
            temps["bed"]["actual"],
            # self._printer.gcode_line_num_no_comments,
            # self._printer.gcode_cmd,
            int(self._settings["nozzle_tip_coords_x"]),
            int(self._settings["nozzle_tip_coords_y"]),
            self._settings["flip_h"],
            self._settings["flip_v"],
            self._settings["rotate"],
        ]
        return row

    def generate_auth_headers(self):
        """
        Generates the authentication headers for API requests.

        Returns:
            dict: The authentication headers.
        """
        return {"Authorization": self._settings["auth_token"]}

    def update_csv(self):
        try:
            self.csv_writer.writerow(self.csv_data_row())
            self.csv_print_log.flush()
        except Exception as e:
            self._logger.error(e)

    def update_image(self):
        try:
            resp = requests.get(self._settings["snapshot_url"], stream=True)     
            self._logger.debug("Image fetched, about to upload")
            self.image_upload(resp.content)
            self.image_count += 1
        except Exception as e:
            self._logger.error(e)

    def data_thread_loop(self):
        """
        Main loop for collecting data:
        - to populate the CSV log
        - to capture image frames

        This loop runs at a rate determined by SAMPLING_TIMEOUT.

        Returns:
            None
        """
        self._logger.info("Starting main data loop method.")
        old_time = time.perf_counter()
        time_buffer = 0.0

        while True:
            current_time = time.perf_counter()
            if (
                self.is_new_job()
                and (current_time - old_time) > SAMPLING_TIMEOUT - time_buffer
            ):
                time_buffer = max(0, current_time - old_time - SAMPLING_TIMEOUT)
                old_time = current_time
                self.update_csv()
                self._logger.debug("CSV updated, about to update image")
                self.update_image()
                # DEBUG COMMAND
                # self._logger.info(self._printer.get_all_print_objects())
            time.sleep(0.1)  # slow things down to 10ms to run other threads!!