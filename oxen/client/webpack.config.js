const path = require('path');

module.exports = {
    entry: './src/app.ts',
    output: { filename: 'oxen.js', path: path.resolve(__dirname, './static/js') },
    resolve: { extensions: ['.ts', '.tsx', '.js'] },
    module: { rules: [{ test: /\.tsx?$/, loader: 'ts-loader' }] },
    devtool: 'source-map',
    mode: 'production'
};
