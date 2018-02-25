from setuptools import setup, find_packages

setup(
    name='oxen',
    version='0.1.0',
    description='Task runner with a web-based frontend',
    author='Saumitro Dasgupta',
    author_email='sd@cs.stanford.edu',
    url='https://github.com/ethereon/oxen',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Programming Language :: Python :: 3.6',
    ],
    packages=find_packages(),
    install_requires=['tornado', 'watchdog'],
    include_package_data=True,
    zip_safe=True,
    license='MIT'
)
