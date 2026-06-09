CREATE ROLE dialin_app LOGIN PASSWORD 'dialin_app';

GRANT CONNECT ON DATABASE dialin TO dialin_app;
