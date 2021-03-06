import numpy
import six

import chainer
from chainer.functions.activation import sigmoid
from chainer.functions.activation import tanh
from chainer.functions.array import concat
from chainer.functions.array import split_axis
from chainer import link
from chainer.links.connection import linear


class GRUBase(link.Chain):

    def __init__(self, n_units, n_inputs=None, init=None,
                 inner_init=None, bias_init=0):
        if n_inputs is None:
            n_inputs = n_units
        super(GRUBase, self).__init__(
            W_r=linear.Linear(n_inputs, n_units,
                              initialW=init, initial_bias=bias_init),
            U_r=linear.Linear(n_units, n_units,
                              initialW=inner_init, initial_bias=bias_init),
            W_z=linear.Linear(n_inputs, n_units,
                              initialW=init, initial_bias=bias_init),
            U_z=linear.Linear(n_units, n_units,
                              initialW=inner_init, initial_bias=bias_init),
            W=linear.Linear(n_inputs, n_units,
                            initialW=init, initial_bias=bias_init),
            U=linear.Linear(n_units, n_units,
                            initialW=inner_init, initial_bias=bias_init),
        )


class GRU(GRUBase):

    """Stateless Gated Recurrent Unit function (GRU).

    GRU function has six parameters :math:`W_r`, :math:`W_z`, :math:`W`,
    :math:`U_r`, :math:`U_z`, and :math:`U`. All these parameters are
    :math:`n \\times n` matrices, where :math:`n` is the dimension of
    hidden vectors.

    Given two inputs a previous hidden vector :math:`h` and an input vector
    :math:`x`, GRU returns the next hidden vector :math:`h'` defined as

    .. math::

       r &=& \\sigma(W_r x + U_r h), \\\\
       z &=& \\sigma(W_z x + U_z h), \\\\
       \\bar{h} &=& \\tanh(W x + U (r \\odot h)), \\\\
       h' &=& (1 - z) \\odot h + z \\odot \\bar{h},

    where :math:`\\sigma` is the sigmoid function, and :math:`\\odot` is the
    element-wise product.

    :class:`~chainer.links.GRU` does not hold the value of
    hidden vector :math:`h`. So this is *stateless*.
    Use :class:`~chainer.links.StatefulGRU` as a *stateful* GRU.

    Args:
        n_units(int): Dimension of hidden vector :math:`h`.
        n_inputs(int): Dimension of input vector :math:`x`. If ``None``,
            it is set to the same value as ``n_units``.

    See:
        - `On the Properties of Neural Machine Translation: Encoder-Decoder
          Approaches <http://www.aclweb.org/anthology/W14-4012>`_
          [Cho+, SSST2014].
        - `Empirical Evaluation of Gated Recurrent Neural Networks on Sequence
          Modeling <http://arxiv.org/abs/1412.3555>`_
          [Chung+NIPS2014 DLWorkshop].


    .. seealso:: :class:`~chainer.links.StatefulGRU`

    """

    def __call__(self, h, x):
        r = sigmoid.sigmoid(self.W_r(x) + self.U_r(h))
        z = sigmoid.sigmoid(self.W_z(x) + self.U_z(h))
        h_bar = tanh.tanh(self.W(x) + self.U(r * h))
        h_new = (1 - z) * h + z * h_bar
        return h_new


class StatefulGRU(GRUBase):
    """Stateful Gated Recurrent Unit function (GRU).

    Stateful GRU function has six parameters :math:`W_r`, :math:`W_z`,
    :math:`W`, :math:`U_r`, :math:`U_z`, and :math:`U`.
    All these parameters are :math:`n \\times n` matrices,
    where :math:`n` is the dimension of hidden vectors.

    Given input vector :math:`x`, Stateful GRU returns the next
    hidden vector :math:`h'` defined as

    .. math::

       r &=& \\sigma(W_r x + U_r h), \\\\
       z &=& \\sigma(W_z x + U_z h), \\\\
       \\bar{h} &=& \\tanh(W x + U (r \\odot h)), \\\\
       h' &=& (1 - z) \\odot h + z \\odot \\bar{h},

    where :math:`h` is current hidden vector.

    As the name indicates, :class:`~chainer.links.StatefulGRU` is *stateful*,
    meaning that it also holds the next hidden vector `h'` as a state.
    Use :class:`~chainer.links.GRU` as a stateless version of GRU.

    Args:
        in_size(int): Dimension of input vector :math:`x`.
        out_size(int): Dimension of hidden vector :math:`h`.
        init: A callable that takes ``numpy.ndarray`` or
            ``cupy.ndarray`` and edits its value.
            It is used for initialization of the
            GRU's input units (:math:`W`). Maybe be `None` to use default
            initialization.
        inner_init: A callable that takes ``numpy.ndarray`` or
            ``cupy.ndarray`` and edits its value.
            It is used for initialization of the GRU's inner
            recurrent units (:math:`U`).
            Maybe be ``None`` to use default initialization.
        bias_init: A callable or scalar used to initialize the bias values for
            both the GRU's inner and input units. Maybe be ``None`` to use
            default initialization.

    Attributes:
        h(~chainer.Variable): Hidden vector that indicates the state of
            :class:`~chainer.links.StatefulGRU`.

    .. seealso:: :class:`~chainer.functions.GRU`

    """

    def __init__(self, in_size, out_size, init=None,
                 inner_init=None, bias_init=0):
        super(StatefulGRU, self).__init__(
            out_size, in_size, init, inner_init, bias_init)
        self.state_size = out_size
        self.reset_state()

    def to_cpu(self):
        super(StatefulGRU, self).to_cpu()
        if self.h is not None:
            self.h.to_cpu()

    def to_gpu(self, device=None):
        super(StatefulGRU, self).to_gpu(device)
        if self.h is not None:
            self.h.to_gpu(device)

    def set_state(self, h):
        assert isinstance(h, chainer.Variable)
        h_ = h
        if self.xp == numpy:
            h_.to_cpu()
        else:
            h_.to_gpu()
        self.h = h_

    def reset_state(self):
        self.h = None

    def __call__(self, x):
        z = self.W_z(x)
        h_bar = self.W(x)
        if self.h is not None:
            r = sigmoid.sigmoid(self.W_r(x) + self.U_r(self.h))
            z += self.U_z(self.h)
            h_bar += self.U(r * self.h)
        z = sigmoid.sigmoid(z)
        h_bar = tanh.tanh(h_bar)

        h_new = z * h_bar
        if self.h is not None:
            h_new += (1 - z) * self.h
        self.h = h_new
        return self.h


class StackedStatelessGRU(link.ChainList):

    """Stacked Stateless Gated Recurrent Unit function (GRU).

    This is an implementation of a Stacked Stateless GRU.
    The underlying idea is to simply stack multiple GRUs
    where the GRU at the bottom takes the regular input,
    and the GRUs after that simply take the outputs
    (represented by h) of the lower GRUs as inputs.
    Since this is a stateless implementation,
    the states of all the GRUs must be returned
    Args:
          in_size (int)- The size of embeddings of the inputs
          out_size (int)- The size of the hidden layer representation of
                      each GRU unit
          num_layers (int)- The number of GRU layers

    Attributes:
          num_layers: Indicates the number of GRU layers
    User Defined Methods:

    """

    def __init__(self, in_size, out_size, num_layers=1):
        super(StackedStatelessGRU, self).__init__()
        assert num_layers >= 1
        self.add_link(GRU(out_size, in_size))
        for i in range(1, num_layers):
            self.add_link(GRU(out_size, out_size))
        self.num_layers = num_layers

    def __call__(self, h, x):
        """Updates the internal state and returns the  GRU outputs.

        Args:
            x (~chainer.Variable): A new batch from the input sequence.
            h (~chainer.Variable): The list of the previous cell outputs.

        Returns:
            ~chainer.Variable: A list of the outputs (h) of the updated
                GRU units over all the layers.

        """
        h_list = []
        h = split_axis.split_axis(h, self.num_layers, 1, True)
        h_curr = x
        for layer, h in six.moves.zip(self, h):
            h_curr = layer(h, h_curr)
            h_list.append(h_curr)
        return concat.concat(h_list, 1)


class StackedStatefulGRU(link.ChainList):

    """Stacked Stateful Gated Recurrent Unit function (GRU).

    This is an implementation of a Stacked Stateful GRU.
    The underlying idea is to simply stack multiple
    Stateful GRUs where the GRU at the bottom takes the regular input,
    and the GRUs after that simply take the outputs (represented by h)
    of the previous GRUs as inputs.

    Args:
          in_size (int)- The size of embeddings of the inputs
          out_size (int)- The size of the hidden layer
                    representation of each GRU unit
          num_layers (int)- The number of GRU layers
    Attributes:
          num_layers (int): Indicates the number of GRU layers
    User Defined Methods:
    """

    def __init__(self, in_size, out_size, num_layers=1):
        super(StackedStatefulGRU, self).__init__()
        assert num_layers >= 1
        self.add_link(StatefulGRU(in_size, out_size))
        for i in range(1, num_layers):
            self.add_link(StatefulGRU(out_size, out_size))
        self.num_layers = num_layers
        self.reset_state()

    def to_cpu(self):
        for layer in self:
            layer.to_cpu()

    def to_gpu(self, device=None):
        for layer in self:
            layer.to_gpu(device)

    def set_state(self, h):
        h = split_axis.split_axis(h, self.num_layers, 1, True)
        for layer, h in six.moves.zip(self, h):
            assert isinstance(h, chainer.Variable)
            layer.set_state(h)

    def reset_state(self):
        for layer in self:
            layer.reset_state()

    def __call__(self, x, top_n=None):
        """Updates the internal state and returns the GRU outputs.

        Args:
            x (~chainer.Variable): A new batch from the input sequence.
            top_n (int): The number of GRUs from the top whose outputs
            you want (default: outputs of all GRUs are returned)

        Returns:
            ~chainer.Variable: A concatenation of the outputs (h) of
            the updated GRU units over the top N layers; by default
            all layers are considered.

        """
        if top_n is None:
            top_n = self.num_layers

        h_list = []
        h_curr = x
        for layer in self:
            h_curr = layer(h_curr)
            h_list.append(h_curr)
        return concat.concat(h_list[-top_n:], 1)
