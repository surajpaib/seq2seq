# -*- coding: utf-8 -*-
from __future__ import absolute_import
import theano
import theano.tensor as T
import numpy as np

from keras import activations, initializations
from keras.utils.theano_utils import shared_zeros, sharedX 
from keras.layers.core import Layer, MaskedLayer
from six.moves import range
from stateful_rnn import StatefulRNN

class LSTMDecoder(StatefulRNN):
    def __init__(self, dim, hidden_dim, output_length,
                 init='glorot_uniform', inner_init='orthogonal', forget_bias_init='one',
                 activation='tanh', inner_activation='hard_sigmoid',
                 weights=None, truncate_gradient=-1,
                 hidden_state=None, batch_size=None, **kwargs):
        self.output_dim = dim
        self.input_dim = dim
        self.hidden_dim = hidden_dim
        self.init = initializations.get(init)
        self.inner_init = initializations.get(inner_init)
        self.forget_bias_init = initializations.get(forget_bias_init)
        self.activation = activations.get(activation)
        self.inner_activation = activations.get(inner_activation)
        self.truncate_gradient = truncate_gradient
        self.initial_weights = weights
        self.initial_state = hidden_state
        self.batch_size = batch_size
        self.output_length = output_length
        kwargs['input_shape'] = (dim,)
        self.input_ndim = 2
        self.return_sequences = True
        super(LSTMDecoder, self).__init__(**kwargs)

    def build(self):

        dim = self.input_dim
        hdim = self.hidden_dim

        self.input = T.matrix()

        self.W_i = self.init((dim, hdim))
        self.U_i = self.inner_init((hdim, hdim))
        self.b_i = shared_zeros((hdim))

        self.W_f = self.init((dim, hdim))
        self.U_f = self.inner_init((hdim, hdim))
        self.b_f = self.forget_bias_init((hdim))

        self.W_c = self.init((dim, hdim))
        self.U_c = self.inner_init((hdim, hdim))
        self.b_c = shared_zeros((hdim))

        self.W_o = self.init((dim, hdim))
        self.U_o = self.inner_init((hdim, hdim))
        self.b_o = shared_zeros((hdim))

        self.W_x = self.init((hdim, dim))
        self.b_x = shared_zeros((dim))
        self.params = [
            self.W_i, self.U_i, self.b_i,
            self.W_c, self.U_c, self.b_c,
            self.W_f, self.U_f, self.b_f,
            self.W_o, self.U_o, self.b_o,
            self.W_x, self.b_x
        ]
        nw = len(self.initial_weights) if self.initial_weights is not None else 0

        if self.initial_state is not None:
            self.h = sharedX(self.initial_state[0])
            self.c = sharedX(self.initial_state[1])
            del self.initial_state
        elif self.batch_size is not None:
            self.h = shared_zeros((self.batch_size, self.hidden_dim))
            self.c = shared_zeros((self.batch_size, self.hidden_dim))                
        elif self.initial_weights is not None:
            if nw == len(self.params) + 2:
                self.h = sharedX(self.initial_weights[-1])
                self.c = sharedX(self.initial_weights[-2])
                nw -= 2
            else:
                    raise Exception("Hidden state not provided in weights")
        else:
            raise Exception("One of the following arguments must be provided for stateful RNNs: hidden_state, batch_size, weights")
        self.state = [self.h, self.c]
        self.params += self.state
        if self.initial_weights is not None:
            self.set_weights(self.initial_weights[:nw])
            del self.initial_weights

    def _step(self,
              x_tm1,
              h_tm1, c_tm1,
              u_i, u_f, u_o, u_c):


        xi_t = T.dot(x_tm1, self.W_i) + self.b_i
        xf_t = T.dot(x_tm1, self.W_f) + self.b_f
        xc_t = T.dot(x_tm1, self.W_c) + self.b_c
        xo_t = T.dot(x_tm1, self.W_o) + self.b_o

        i_t = self.inner_activation(xi_t + T.dot(h_tm1, u_i))
        f_t = self.inner_activation(xf_t + T.dot(h_tm1, u_f))
        c_t = f_t * c_tm1 + i_t * self.activation(xc_t + T.dot(h_tm1, u_c))
        o_t = self.inner_activation(xo_t + T.dot(h_tm1, u_o))
        h_t = o_t * self.activation(c_t)

        x_t = T.dot(h_t, self.W_x) + self.b_x
        return x_t, h_t, c_t

    def get_output(self, train=False):
        x_t = self.get_input(train)          
        [outputs,hidden_states, cell_states], updates = theano.scan(
            self._step,
            n_steps = self.output_length,
            outputs_info=[x_t, self.h, self.h],
            non_sequences=[self.U_i, self.U_f, self.U_o, self.U_c],
            truncate_gradient=self.truncate_gradient)
        self.updates = ((self.h, outputs[-1][0]),(self.c, outputs[-1][1]) )
        return outputs

    def get_config(self):
        config = {"name": self.__class__.__name__,
                  "output_dim": self.output_dim,
                  "init": self.init.__name__,
                  "inner_init": self.inner_init.__name__,
                  "forget_bias_init": self.forget_bias_init.__name__,
                  "activation": self.activation.__name__,
                  "inner_activation": self.inner_activation.__name__,
                  "truncate_gradient": self.truncate_gradient,
                  "input_dim": self.input_dim,
                  "output_length": self.output_length
                  }
        base_config = super(FeedbackLSTM, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))
    def set_weights(self, weights):
        assert len(self.params) == len(weights), 'Provided weight array does not match layer weights (' + \
            str(len(self.params)) + ' layer params vs. ' + str(len(weights)) + ' provided weights)'
        for p, w in zip(self.params, weights):
            if p.eval().shape != w.shape:
                raise Exception("Layer shape %s not compatible with weight shape %s." % (p.eval().shape, w.shape))
            p.set_value(floatX(w))

    def get_hidden_state(self):
        state = [h.get_value() for h in self.state]
        return state

    def set_hidden_state(self, state):
        if len(state) != len(self.state):
            raise Exception("Provided hidden state array does not match layer hidden states")
        for s, h in zip(self.state, state):
            if s.eval().shape != h.shape:
                raise Exception("Hidden state shape not compatible")
            s.set_value(floatX(h))

    def reset_hidden_state(self):
        for h in self.state:
            h.set_value(h.get_value()*0)

    @property
    def output_shape(self):
        input_shape = self.input_shape
        return (input_shape[0], self.output_length, self.output_dim)
