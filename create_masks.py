import os
import time
import argparse
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass

import numpy as np
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from fake_useragent import UserAgent


# Thread-safe for counting proceeded images
lock = threading.Lock()
proceeded_cnt = 0


class STATUS_CODE(Enum):
    NOT_OK = 0
    OK = 1


@dataclass
class Result:
    status: str = STATUS_CODE.OK


def find_element(driver, selector, timeout, until='presence'):
    wait = WebDriverWait(driver, timeout)
    if until == 'presence':
        try:
            return wait.until(EC.presence_of_element_located(selector))
        except TimeoutError:
            print(f'Timeout for selector: {selector}')
            return
    elif until == 'visiable':
        try:
            return wait.until(EC.visibility_of_element_located(selector))
        except TimeoutException:
            print(f'Timeout for selector: {selector}')
    else:
        raise ValueError('Not supported until type')


def wait_element_to_clickable(element, timeout: int = 30):
    t0 = time.time()
    while True:
        try:
            if time.time() - t0 > timeout:
                return

            element.click()
            return element
        except Exception as e:
            time.sleep(1)


def wait_until_presence_of_file_path(file_path: str, timeout: int = 30):
    t0 = time.time()
    while True:
        try:
            if time.time() - t0 > timeout:
                return

            if os.path.isfile(file_path):
                return file_path
        except Exception as e:
            time.sleep(1)


def setup(args):
    options = Options()
    ua = UserAgent()
    userAgent = ua.random
    options.add_argument(f'user-agent={userAgent}')
    options.add_argument('--start-maximized')
    options.add_argument('--headless')
    options.add_argument('--disabled-gpu')
    options.add_experimental_option('prefs', {'download.default_directory': args.download_dir})
    chromedriver_path = Path(__file__).parents[0] / 'chromedriver'
    driver = webdriver.Chrome(executable_path=chromedriver_path, options=options)
    driver.execute_script("return navigator.userAgent")
    return driver


def create_mask_single_image(driver, image_path):
    # Upload image
    input_selector = '#root > div.flex.h-screen.w-screen.overflow-hidden > div.relative.flex.h-full.grow.flex-col.overflow-y-auto.bg-white > div.grow > div > div.mb-8.lg\:-mx-8 > div > div > input'
    input = find_element(driver, (By.CSS_SELECTOR, input_selector), 30)
    if input is None:
        return Result(status=STATUS_CODE.NOT_OK)

    input.send_keys(image_path)

    # Set transparent background
    bg_selector_btn_selector = '#root > div.flex.h-screen.w-screen.overflow-hidden > div.relative.flex.h-full.grow.flex-col.overflow-y-auto.bg-white > div.grow.overflow-hidden > div > div > div.relative.order-3.h-full.shrink-0 > div > div > div > div > ul > li:nth-child(2)'
    bg_selector_btn = find_element(driver, (By.CSS_SELECTOR, bg_selector_btn_selector), 30)
    if bg_selector_btn is None:
        return Result(status=STATUS_CODE.NOT_OK)
    bg_selector_btn.click()

    nobg_btn_selector = '#root > div.flex.h-screen.w-screen.overflow-hidden > div.relative.flex.h-full.grow.flex-col.overflow-y-auto.bg-white > div.grow.overflow-hidden > div > div > div.relative.order-3.h-full.shrink-0 > div > div > div > div > div.space-y-4 > div:nth-child(3) > div > div > div.flex.flex-wrap.gap-2 > button.group.relative.overflow-hidden.rounded-full.shadow-\[inset_0_0_0_1px_rgba\(34\,37\,71\,0\.15\)\].w-6.h-6.ring-2.ring-black.ring-offset-2'
    nobg_btn = find_element(driver, (By.CSS_SELECTOR, nobg_btn_selector), 30)
    if nobg_btn is None:
        return Result(status=STATUS_CODE.NOT_OK)
    nobg_btn.click()

    # Find out download button
    wait = WebDriverWait(driver, 30)
    span = wait.until(EC.presence_of_element_located((By.XPATH, "//span[text()='Download']")), 30)
    download_btn = span.find_element(By.XPATH, '../../..')
    success = wait_element_to_clickable(download_btn, 30)
    if not success:
        return Result(status=STATUS_CODE.NOT_OK)

    # Find out continue button
    wait = WebDriverWait(driver, 30)
    span = wait.until(EC.presence_of_element_located((By.XPATH, "//span[text()='Continue']")), 30)
    continue_btn = span.find_element(By.XPATH, '../../..')
    success = wait_element_to_clickable(continue_btn, 30)
    if not success:
        return Result(status=STATUS_CODE.NOT_OK)
    return Result(status=STATUS_CODE.OK)


def get_filename_wo_ext(filename: str):
    return filename[:filename.rfind('.')]


def load_image_paths(image_dir: str):
    image_paths = [str(p) for p in Path(image_dir).glob('*.jpg')]
    return image_paths


def run(driver, image_paths: list, outdir: str, total_image: int):
    global proceeded_cnt

    os.makedirs(outdir, exist_ok=True)

    login_base_url = 'https://app.photoroom.com/create'
    default_download_dir = os.path.expanduser('~/Downloads')
    for image_path in image_paths:
        driver.get(login_base_url)

        result = create_mask_single_image(driver, image_path)
        if result.status == STATUS_CODE.NOT_OK:
            print(f'Failed {image_path}')
            continue

        image_filename = os.path.basename(image_path)
        image_download_filename = get_filename_wo_ext(image_filename) + '-PhotoRoom.png'
        image_download_path = os.path.join(default_download_dir, image_download_filename)
        success = wait_until_presence_of_file_path(image_download_path)
        if not success:
            print(f'Not found transparent background image: {image_download_path}')
            continue

        dst_image_path = os.path.join(outdir, image_download_filename)

        im0 = np.array(Image.open(image_download_path))
        idx = 1200
        im0[idx:, :, :] = 0
        Image.fromarray(im0).save(dst_image_path)
        if os.path.isfile(image_download_path):
            os.remove(image_download_path)

        with lock:
            proceeded_cnt += 1
            print(f'Proceeding {proceeded_cnt}/{total_image}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=str, help='Image directory')
    parser.add_argument('--workers', type=str, default=2,
                        help='Number of parallel threads')
    parser.add_argument('--download_dir', type=str, default='~/Downloads',
                        help='Temporary download location')
    parser.add_argument('--headless', type=bool, default=False,
                        action='store_true', help='Whether to use headless mode')
    args = parser.parse_args()
    print(args)

    image_dir = args.source
    image_paths = load_image_paths(image_dir)
    max_threads = args.workers

    # workers
    batch_size = len(image_paths) // max_threads
    all_threads = []
    for i in range(max_threads):
        driver = setup(args)
        start = i * batch_size
        end = min((i + 1) * batch_size, len(image_paths))
        sub_image_paths = image_paths[start:end]
        t = threading.Thread(target=run, args=(driver, sub_image_paths, f'outputs/part_{i}', len(image_paths)))
        t.start()
        all_threads.append(t)

    for t in all_threads:
        t.join()
    print('DONE!')