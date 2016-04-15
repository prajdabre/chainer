import unittest

import numpy

import chainer
from chainer import cuda
from chainer import gradient_check
from chainer import links
from chainer import testing
from chainer.testing import attr


def _sigmoid(x):
    xp = cuda.get_array_module(x)
    return 1 / (1 + xp.exp(-x))


def _gru(func, h, x):
    y = None
    
    if isinstance(func, links.StackedGRU) or isinstance(func, links.StackedStatefulGRU):
        y = []
        xp = cuda.get_array_module(h[0], x)
        
        r = _sigmoid(x.dot(func[0].W_r.W.data.T) + h[0].dot(func[0].U_r.W.data.T))
        z = _sigmoid(x.dot(func[0].W_z.W.data.T) + h[0].dot(func[0].U_z.W.data.T))
        h_bar = xp.tanh(x.dot(func[0].W.W.data.T) + (r * h[0]).dot(func[0].U.W.data.T))
        y_curr = (1 - z) * h[0] + z * h_bar
        y.append(y_curr)
        for i in range(1:func.num_layers):
            r = _sigmoid(y_curr.dot(func[i].W_r.W.data.T) + h[i].dot(func[i].U_r.W.data.T))
            z = _sigmoid(y_curr.dot(func[i].W_z.W.data.T) + h[i].dot(func[i].U_z.W.data.T))
            h_bar = xp.tanh(y_curr.dot(func[i].W.W.data.T) + (r * h[i]).dot(func[i].U.W.data.T))
            y_curr = (1 - z) * h[i] + z * h_bar
            y.append(y_curr)
        
    else:
        xp = cuda.get_array_module(h, x)

        r = _sigmoid(x.dot(func.W_r.W.data.T) + h.dot(func.U_r.W.data.T))
        z = _sigmoid(x.dot(func.W_z.W.data.T) + h.dot(func.U_z.W.data.T))
        h_bar = xp.tanh(x.dot(func.W.W.data.T) + (r * h).dot(func.U.W.data.T))
        y = (1 - z) * h + z * h_bar
    return y



@testing.parameterize(
    {'gru': links.GRU, 'state': 'random', 'in_size': 4, 'out_size': 8},
    {'gru': links.GRU, 'state': 'random', 'out_size': 8},
    {'gru': links.StatefulGRU, 'state': 'random', 'in_size': 4, 'out_size': 8},
    {'gru': links.StatefulGRU, 'state': 'zero', 'in_size': 4, 'out_size': 8},
    {'gru': links.StackedGRU, 'state': 'random', 'in_size': 4, 'out_size': 8, 'num_layers': 5},
    {'gru': links.StackedGRU, 'state': 'zero', 'in_size': 4, 'out_size': 8, 'num_layers': 5},
    {'gru': links.StackedStatefulGRU, 'state': 'random', 'in_size': 4, 'out_size': 8, 'num_layers': 5},
    {'gru': links.StackedStatefulGRU, 'state': 'zero', 'in_size': 4, 'out_size': 8, 'num_layers': 5},
)
class TestGRU(unittest.TestCase):

    def setUp(self):
        if self.gru == links.GRU:
            if hasattr(self, 'in_size'):
                self.link = self.gru(self.out_size, self.in_size)
            else:
                self.link = self.gru(self.out_size)
                self.in_size = self.out_size
        elif self.gru == links.StatefulGRU:
            self.link = self.gru(self.in_size, self.out_size)
        elif self.gru == links.StackedGRU:
            self.link = self.gru(self.in_size, self.out_size, self.num_layers)
        elif self.gru == links.StackedStatefulGRU:
            self.link = self.gru(self.in_size, self.out_size, self.num_layers)
        else:
            self.fail('Unsupported link(only GRU and StatefulGRU '
                      'are supported):{}'.format(self.gru))

        self.x = numpy.random.uniform(
            -1, 1, (3, self.in_size)).astype(numpy.float32)
        if self.state == 'random':
            if self.gru == links.StackedGRU or self.gru == links.StackedStatefulGRU
                self.h = [numpy.random.uniform(
                    -1, 1, (3, self.out_size)).astype(numpy.float32) for _ in range(self.num_layers)]
            else:
                self.h = numpy.random.uniform(
                    -1, 1, (3, self.out_size)).astype(numpy.float32)
        elif self.state == 'zero':
            if self.gru == links.StackedGRU or self.gru == links.StackedStatefulGRU
                self.h = [numpy.zeros((3, self.out_size), dtype=numpy.float32) for _ in range(self.num_layers)]
            else:
                self.h = numpy.zeros((3, self.out_size), dtype=numpy.float32)
        else:
            self.fail('Unsupported state initialization:{}'.format(self.state))
        if self.gru == links.StackedGRU or self.gru == links.StackedStatefulGRU
            self.gy = [numpy.random.uniform(
                -1, 1, (3, self.out_size)).astype(numpy.float32) for _ in range(self.num_layers)]
        else:
            self.gy = numpy.random.uniform(
                -1, 1, (3, self.out_size)).astype(numpy.float32)

    def _forward(self, link, h, x):
        if isinstance(link, links.GRU) or isinstance(link, links.StackedGRU):
            return link(h, x)
        else:
            if self.state != 'zero':
                link.set_state(h)
            return link(x)

    def check_forward(self, h_data, x_data):
        h = [chainer.Variable(h_dat) for h_dat in h_data] if isinstance(self.link, links.StackedGRU) or isinstance(self.link, links.StackedStatefulGRU) else chainer.Variable(h_data)
        x = chainer.Variable(x_data)
        y = self._forward(self.link, h, x)
        y_expect = _gru(self.link, h_data, x_data)
        if isinstance(self.link, links.StackedGRU) or isinstance(self.link, links.StackedStatefulGRU):
            for y_inner, y_inner_expect in zip(y,y_expect):
                self.assertEqual(y_inner.data.dtype, numpy.float32)
                gradient_check.assert_allclose(y_inner_expect, y_inner.data)
        else:
             self.assertEqual(y.data.dtype, numpy.float32)
             gradient_check.assert_allclose(y_expect, y.data)
        
        if isinstance(self.link, links.StatefulGRU):
            gradient_check.assert_allclose(self.link.h.data, y.data)
        if isinstance(self.link, links.StackedStatefulGRU):
            for i in range(self.link.num_layers):
                gradient_check.assert_allclose(self.link[i].h.data, y[i].data)

    def test_forward_cpu(self):
        self.check_forward(self.h, self.x)

    @attr.gpu
    def test_forward_gpu(self):
        self.link.to_gpu()
        self.check_forward(cuda.to_gpu(self.h),
                           cuda.to_gpu(self.x))

    def check_backward(self, h_data, x_data, y_grad):
        h = [chainer.Variable(h_dat) for h_dat in h_data]
        x = chainer.Variable(x_data)
        y = self._forward(self.link, h, x)
        y.grad = y_grad
        y.backward()

        def f():
            return _gru(self.link, h_data, x_data),
        gx, = gradient_check.numerical_grad(f, (x.data,), (y.grad,))
        gradient_check.assert_allclose(gx, x.grad, atol=1e-3)

        if isinstance(self.link, links.GRU):
            gh, = gradient_check.numerical_grad(f, (h.data,), (y.grad,))
            gradient_check.assert_allclose(gh, h.grad, atol=1e-3)

    def test_backward_cpu(self):
        self.check_backward(self.h, self.x, self.gy)

    @attr.gpu
    def test_backward_gpu(self):
        self.link.to_gpu()
        self.check_backward(cuda.to_gpu(self.h),
                            cuda.to_gpu(self.x),
                            cuda.to_gpu(self.gy))


@testing.parameterize(
    *testing.product({
        'link_array_module': ['to_cpu', 'to_gpu'],
        'state_array_module': ['to_cpu', 'to_gpu']
    }))
class TestGRUState(unittest.TestCase):

    def setUp(self):
        in_size, out_size = 10, 8
        self.link = links.StatefulGRU(in_size, out_size)
        self.h = chainer.Variable(
            numpy.random.uniform(-1, 1, (3, out_size)).astype(numpy.float32))

    def check_set_state(self, h):
        self.link.set_state(h)
        self.assertIsInstance(self.link.h.data, self.link.xp.ndarray)

    def test_set_state_cpu(self):
        self.check_set_state(self.h)

    @attr.gpu
    def test_set_state_gpu(self):
        getattr(self.link, self.link_array_module)()
        getattr(self.h, self.state_array_module)()
        self.check_set_state(self.h)

    def check_reset_state(self):
        self.link.reset_state()
        self.assertIsNone(self.link.h)

    def test_reset_state_cpu(self):
        self.check_reset_state()

    @attr.gpu
    def test_reset_state_gpu(self):
        getattr(self.link, self.link_array_module)()
        self.check_reset_state()


class TestGRUToCPUToGPU(unittest.TestCase):

    def setUp(self):
        in_size, out_size = 10, 8
        self.link = links.StatefulGRU(in_size, out_size)
        self.h = chainer.Variable(
            numpy.random.uniform(-1, 1, (3, out_size)).astype(numpy.float32))

    def check_to_cpu(self, h):
        self.link.set_state(h)
        self.link.to_cpu()
        self.assertIsInstance(self.link.h.data, self.link.xp.ndarray)
        self.link.to_cpu()
        self.assertIsInstance(self.link.h.data, self.link.xp.ndarray)

    def test_to_cpu_cpu(self):
        self.check_to_cpu(self.h)

    @attr.gpu
    def test_to_cpu_gpu(self):
        self.h.to_gpu()
        self.check_to_cpu(self.h)

    def check_to_cpu_to_gpu(self, h):
        self.link.set_state(h)
        self.link.to_gpu()
        self.assertIsInstance(self.link.h.data, self.link.xp.ndarray)
        self.link.to_gpu()
        self.assertIsInstance(self.link.h.data, self.link.xp.ndarray)
        self.link.to_cpu()
        self.assertIsInstance(self.link.h.data, self.link.xp.ndarray)
        self.link.to_gpu()
        self.assertIsInstance(self.link.h.data, self.link.xp.ndarray)

    @attr.gpu
    def test_to_cpu_to_gpu_cpu(self):
        self.check_to_cpu_to_gpu(self.h)

    @attr.gpu
    def test_to_cpu_to_gpu_gpu(self):
        self.h.to_gpu()
        self.check_to_cpu_to_gpu(self.h)


testing.run_module(__name__, __file__)
