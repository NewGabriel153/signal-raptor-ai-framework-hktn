FROM node:16

# Set the working directory
WORKDIR /app

# Copy package metadata, including a lockfile when present
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY . .

# Expose the port the app runs on
EXPOSE 5173

# Command to run the application
CMD ["npm", "run", "dev"]