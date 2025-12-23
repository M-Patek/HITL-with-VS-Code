const path = require('path');
const webpack = require('webpack');

/** @typedef {import('webpack').Configuration} WebpackConfig */

/** @type WebpackConfig */
const webExtensionConfig = {
  mode: 'none', 
  target: 'webworker', 
  entry: {
    extension: './src/extension.ts', 
  },
  output: {
    filename: '[name].js',
    path: path.join(__dirname, './dist'),
    libraryTarget: 'commonjs',
    devtoolModuleFilenameTemplate: '../../[resource-path]'
  },
  resolve: {
    mainFields: ['browser', 'module', 'main'], 
    extensions: ['.ts', '.js'], 
    alias: {
      '@': path.resolve(__dirname, 'src')
    },
    fallback: {
      "path": require.resolve("path-browserify"),
      "child_process": false // Web worker 不支持子进程，这里只是声明
    }
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: [
          {
            loader: 'ts-loader'
          }
        ]
      }
    ]
  },
  plugins: [
    new webpack.ProvidePlugin({
      process: 'process/browser', 
    }),
  ],
  externals: {
    'vscode': 'commonjs vscode', 
  },
  performance: {
    hints: false
  },
  devtool: 'nosources-source-map', 
};

// Node.js 环境配置 (我们的主战场)
/** @type WebpackConfig */
const nodeExtensionConfig = {
    mode: 'none', 
    target: 'node', 
    entry: {
      extension: './src/extension.ts', 
    },
    output: {
      filename: '[name].js',
      path: path.join(__dirname, './dist'),
      libraryTarget: 'commonjs',
      devtoolModuleFilenameTemplate: '../../[resource-path]'
    },
    resolve: {
      mainFields: ['module', 'main'], 
      extensions: ['.ts', '.js'],
      alias: {
        '@': path.resolve(__dirname, 'src')
      }
    },
    module: {
      rules: [
        {
          test: /\.ts$/,
          exclude: /node_modules/,
          use: [
            {
              loader: 'ts-loader'
            }
          ]
        }
      ]
    },
    externals: {
      'vscode': 'commonjs vscode', 
    },
    performance: {
      hints: false
    },
    devtool: 'nosources-source-map', 
  };
  

module.exports = [ nodeExtensionConfig ];
