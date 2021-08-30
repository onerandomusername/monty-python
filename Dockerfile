FROM python:3.9-slim

# Set pip to have cleaner logs and no saved cache
ENV PIP_NO_CACHE_DIR=false


# Create the working directory
WORKDIR /bot

# Copy the source code in last to optimize rebuilding the image
COPY . .

# Install project dependencies
RUN pip install -r requirements.txt

CMD ["python", "-m", "bot"]
