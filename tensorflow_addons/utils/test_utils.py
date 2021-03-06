# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Utilities for testing Addons."""

import contextlib
import inspect
import unittest
import random

import numpy as np
import pytest
import tensorflow as tf

from tensorflow_addons.utils import resource_loader

# TODO: copy the layer_test implementation in Addons.
from tensorflow.python.keras.testing_utils import layer_test  # noqa: F401


@contextlib.contextmanager
def device(use_gpu):
    """Uses gpu when requested and available."""
    if use_gpu and tf.test.is_gpu_available():
        dev = "/device:GPU:0"
    else:
        dev = "/device:CPU:0"
    with tf.device(dev):
        yield


@contextlib.contextmanager
def use_gpu():
    """Uses gpu when requested and available."""
    with device(use_gpu=True):
        yield


def create_virtual_devices(
    num_devices, force_device=None, memory_limit_per_device=1024
):
    """Virtualize a the physical device into logical devices.

    Args:
        num_devices: The number of virtual devices needed.
        force_device: 'CPU'/'GPU'. Defaults to None, where the
            devices is selected based on the system.
        memory_limit_per_device: Specify memory for each
            virtual GPU. Only for GPUs.

    Returns:
        virtual_devices: A list of virtual devices which can be passed to
            tf.distribute.MirroredStrategy()
    """
    if force_device is None:
        device_type = (
            "GPU" if len(tf.config.list_physical_devices("GPU")) > 0 else "CPU"
        )
    else:
        assert force_device in ["CPU", "GPU"]
        device_type = force_device

    physical_devices = tf.config.list_physical_devices(device_type)

    if device_type == "CPU":
        memory_limit_per_device = None

    tf.config.experimental.set_virtual_device_configuration(
        physical_devices[0],
        [
            tf.config.experimental.VirtualDeviceConfiguration(
                memory_limit=memory_limit_per_device
            )
            for _ in range(num_devices)
        ],
    )

    return tf.config.experimental.list_logical_devices(device_type)


def run_all_distributed(num_devices):
    base_decorator = run_distributed(num_devices)

    def decorator(cls):
        for name, method in cls.__dict__.copy().items():
            if (
                callable(method)
                and name.startswith(unittest.TestLoader.testMethodPrefix)
                and name != "test_session"
            ):
                setattr(cls, name, base_decorator(method))
        return cls

    return decorator


# TODO: Add support for other distribution strategies
def run_distributed(num_devices):
    def decorator(f):
        if inspect.isclass(f):
            raise TypeError(
                "`run_distributed` only supports test methods. "
                "Did you mean to use `run_all_distributed`?"
            )

        def decorated(self, *args, **kwargs):
            logical_devices = create_virtual_devices(num_devices)
            strategy = tf.distribute.MirroredStrategy(logical_devices)
            with strategy.scope():
                f(self, *args, **kwargs)

        return decorated

    return decorator


def finalizer():
    tf.config.experimental_run_functions_eagerly(False)


@pytest.fixture(scope="function", params=["eager_mode", "tf_function"])
def maybe_run_functions_eagerly(request):
    if request.param == "eager_mode":
        tf.config.experimental_run_functions_eagerly(True)
    elif request.param == "tf_function":
        tf.config.experimental_run_functions_eagerly(False)

    request.addfinalizer(finalizer)


@pytest.fixture(scope="function", params=["CPU", "GPU"])
def cpu_and_gpu(request):
    if request.param == "CPU":
        with tf.device("/device:CPU:0"):
            yield
    else:
        if not tf.test.is_gpu_available():
            pytest.skip("GPU is not available.")
        with tf.device("/device:GPU:0"):
            yield


@pytest.fixture(scope="function", params=["channels_first", "channels_last"])
def data_format(request):
    return request.param


@pytest.fixture(scope="function", autouse=True)
def set_seeds():
    random.seed(0)
    np.random.seed(0)
    tf.random.set_seed(0)


def pytest_addoption(parser):
    parser.addoption(
        "--skip-custom-ops",
        action="store_true",
        help="When a custom op is being loaded in a test, skip this test.",
    )


@pytest.fixture(scope="session", autouse=True)
def set_global_variables(request):
    if request.config.getoption("--skip-custom-ops"):
        resource_loader.SKIP_CUSTOM_OPS = True


def assert_allclose_according_to_type(
    a,
    b,
    rtol=1e-6,
    atol=1e-6,
    float_rtol=1e-6,
    float_atol=1e-6,
    half_rtol=1e-3,
    half_atol=1e-3,
    bfloat16_rtol=1e-2,
    bfloat16_atol=1e-2,
):
    """
    Similar to tf.test.TestCase.assertAllCloseAccordingToType()
    but this doesn't need a subclassing to run.
    """
    a = np.array(a)
    b = np.array(b)
    # types with lower tol are put later to overwrite previous ones.
    if (
        a.dtype == np.float32
        or b.dtype == np.float32
        or a.dtype == np.complex64
        or b.dtype == np.complex64
    ):
        rtol = max(rtol, float_rtol)
        atol = max(atol, float_atol)
    if a.dtype == np.float16 or b.dtype == np.float16:
        rtol = max(rtol, half_rtol)
        atol = max(atol, half_atol)
    if a.dtype == tf.bfloat16.as_numpy_dtype or b.dtype == tf.bfloat16.as_numpy_dtype:
        rtol = max(rtol, bfloat16_rtol)
        atol = max(atol, bfloat16_atol)

    np.testing.assert_allclose(a, b, rtol=rtol, atol=atol)
