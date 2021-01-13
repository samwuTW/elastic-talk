import os
from setuptools import setup, find_packages


with open("../README.md", "r") as fh:
    long_description = fh.read()


with open('../requirements/base.in', 'r') as f:
    requires = f.read().splitlines()


setup(
    name='elastictalk',
    version=os.environ['CIRCLE_TAG'],
    description='Extend elastic beanstalk cli tool',
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        'Programming Language :: Python :: 3.8',
    ],
    keywords='AWS Elastic Beanstalk',
    author='lambdaTW',
    author_email='lambda@lambda.tw',
    license='MIT',
    packages=find_packages(),
    install_requires=requires,
    entry_points={
        'console_scripts': ['et=elastictalk.scripts.elastictalk:main'],
    },
    zip_safe=False,
)
