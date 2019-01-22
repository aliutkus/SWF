from __future__ import print_function
import argparse
import torch.utils.data
import torch
from torch import nn, optim
from torch.nn import functional as F
from torchvision import datasets, transforms
from torchvision.utils import save_image
import numpy as np
import os


class ConvEncoder(nn.Module):
    def __init__(self, input_shape, bottleneck_size=64):
        super(ConvEncoder, self).__init__()
        self.input_shape = input_shape
        self.conv1 = nn.Conv2d(self.input_shape[0], 3, kernel_size=3, stride=1, padding=1)
        self.conv2 = nn.Conv2d(3, 32, kernel_size=2, stride=2, padding=0)
        self.conv3 = nn.Conv2d(32, 32, kernel_size=3, stride=1, padding=1)
        self.conv4 = nn.Conv2d(32, 32, kernel_size=3, stride=1, padding=1)
        self.relu = nn.ReLU()
        self.fc1 = nn.Linear(16 * 16 * 32, bottleneck_size)

    def forward(self, x):
        if len(x.shape) == 3:
            x = x[None, ...]

        out = self.relu(self.conv1(x))
        out = self.relu(self.conv2(out))
        out = self.relu(self.conv3(out))
        out = self.relu(self.conv4(out))
        out = out.view(out.size(0), -1)
        return self.relu(self.fc1(out))


class ConvDecoder(nn.Module):
    def __init__(self, input_shape, bottleneck_size=64):
        super(ConvDecoder, self).__init__()
        self.input_shape = input_shape
        self.fc4 = nn.Linear(bottleneck_size, 8192)
        self.deconv1 = nn.ConvTranspose2d(32, 32, kernel_size=3, stride=1, padding=1)
        self.deconv2 = nn.ConvTranspose2d(32, 32, kernel_size=3, stride=1, padding=1)
        self.deconv3 = nn.ConvTranspose2d(32, 32, kernel_size=2, stride=2, padding=0)
        self.conv5 = nn.Conv2d(32, self.input_shape[0], kernel_size=3, stride=1, padding=1)
        self.relu = nn.ReLU()
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out = self.relu(self.fc4(x))
        out = out.view(out.size(0), 32, 16, 16)
        out = self.relu(self.deconv1(out))
        out = self.relu(self.deconv2(out))
        out = self.relu(self.deconv3(out))
        return self.sigmoid(self.conv5(out))


class DenseEncoder(nn.Module):
    def __init__(self, input_shape, bottleneck_size=64):
        super(DenseEncoder, self).__init__()
        self.input_shape = input_shape
        self.fc1 = nn.Linear(np.prod(input_shape), bottleneck_size)

    def forward(self, x):
        return torch.sigmoid(self.fc1(x.view(-1, np.prod(self.input_shape))))


class DenseDecoder(nn.Module):
    def __init__(self, input_shape, bottleneck_size=64):
        super(DenseDecoder, self).__init__()
        self.input_shape = input_shape
        self.fc1 = nn.Linear(bottleneck_size, np.prod(input_shape))

    def forward(self, x):
        return torch.sigmoid(self.fc1(x)).view(
            -1, self.input_shape[0], self.input_shape[1], self.input_shape[2]
        )


class AutoEncoderModel(nn.Module):
    def __init__(self, input_shape=(1, 28, 28), bottleneck_size=64,
                 convolutive=False):
        super(AutoEncoderModel, self).__init__()
        self.input_shape = input_shape
        self.encode = (ConvEncoder(input_shape, bottleneck_size)
                       if convolutive
                       else DenseEncoder(input_shape, bottleneck_size))
        self.decode = (ConvDecoder(input_shape, bottleneck_size)
                       if convolutive
                       else DenseDecoder(input_shape, bottleneck_size))

    def encode_nograd(self, x):
        with torch.no_grad():
            return self.encode(x)

    def decode_nograd(self, x):
        with torch.no_grad():
            return self.decode(x)

    def forward(self, x):
        return self.decode(self.encode(x))


class AE(object):
    def __init__(self, input_shape, device, bottleneck_size=64,
                 convolutive=False):
        super(AE, self).__init__()
        self.bottleneck_size = bottleneck_size
        self.device = device
        self.criterion = nn.BCELoss()
        self.input_shape = input_shape
        self.model = AutoEncoderModel(
            input_shape=self.input_shape,
            bottleneck_size=self.bottleneck_size,
            convolutive=convolutive
        ).to(device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=1e-3)

    def train(self, data_loader, nb_epochs=10):
        for epoch in range(1, nb_epochs + 1):
            self.model.train()
            train_loss = 0
            for batch_idx, (X, _) in enumerate(data_loader):
                X = X.to(self.device)
                self.optimizer.zero_grad()
                Y = self.model(X)
                loss = self.criterion(Y, X)
                loss.backward()
                train_loss += loss.item()
                self.optimizer.step()

            print('AE train => Epoch: {} Average loss: {:.4f}'.format(
                epoch, train_loss / len(data_loader.dataset)))

    def test(self, data_loader):
        self.model.eval()
        test_loss = 0
        with torch.no_grad():
            for i, (X, _) in enumerate(data_loader):
                X = X.to(device)
                Y = self.model(X)
                test_loss += self.criterion(Y, X).item()
                if i == 0:
                    n = min(X.size(0), 8)
                    comparison = torch.cat([
                        X[:n],
                        Y.view(data_loader.batch_size, 1, 32, 32)[:n]
                    ])
                    save_image(
                        comparison.cpu(),
                        'results/reconstruction.png',
                        nrow=n
                    )

        test_loss /= len(test_loader.dataset)
        print('AE test => Test set loss: {:.4f}'.format(test_loss))


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='AE MNIST Example')
    parser.add_argument('--batch-size', type=int, default=128, metavar='N',
                        help='input batch size for training (default: 128)')
    parser.add_argument('--epochs', type=int, default=20, metavar='N',
                        help='number of epochs to train (default: 20)')
    parser.add_argument('--no-cuda', action='store_true', default=False,
                        help='enables CUDA training')
    parser.add_argument('--seed', type=int, default=1, metavar='S',
                        help='random seed (default: 1)')
    parser.add_argument('--log-interval', type=int, default=10, metavar='N',
                        help='how many batches to wait before logging training status')
    parser.add_argument("--train_ae",
                        help="Force training of the AE.",
                        action="store_true")
    parser.add_argument("--ae_model", default="ae.model",
                        help="filename for the autoencoder model")

    args = parser.parse_args()
    args.cuda = not args.no_cuda and torch.cuda.is_available()

    torch.manual_seed(args.seed)

    device = torch.device("cuda" if args.cuda else "cpu")

    kwargs = {'num_workers': 1, 'pin_memory': True} if args.cuda else {}

    # set transforms
    tr = transforms.Compose(
        [
            transforms.Resize(32),
            transforms.ToTensor()
        ]
    )

    train_loader = torch.utils.data.DataLoader(
        datasets.MNIST(
            '../data',
            train=True,
            download=True,
            transform=tr
        ),
        batch_size=args.batch_size, shuffle=True, **kwargs
    )
    test_loader = torch.utils.data.DataLoader(
        datasets.MNIST('../data', train=False, transform=tr),
        batch_size=args.batch_size, shuffle=True, **kwargs)

    autoencoder = AE(
        train_loader.dataset[0][0].shape,
        device=device,
        bottleneck_size=64
    )

    if args.train_ae:
        if not os.path.exists(args.ae_model):
            print('training AE on', device)
            autoencoder.train(train_loader, nb_epochs=30)
            autoencoder.model = autoencoder.model.to('cpu')
            if args.ae_model is not None:
                torch.save(autoencoder.model.state_dict(), args.ae_model)
    else:
        print("Model loaded")
        state = torch.load(args.ae_model, map_location='cpu')
        autoencoder.model.to('cpu').load_state_dict(state)

    autoencoder.test(test_loader)
    with torch.no_grad():
        sample = torch.randn(32, 64).to(device)
        sample = autoencoder.model.decode(sample).cpu()
        save_image(
            sample.view(32, 1, 32, 32),
            'results/sample.png'
        )
