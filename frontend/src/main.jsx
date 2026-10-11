import React from 'react';
import {createRoot} from 'react-dom/client';
import {Phase04App} from './app/router.jsx';
import './styles.css';
import './auth/auth.css';

createRoot(document.getElementById('root')).render(<React.StrictMode><Phase04App/></React.StrictMode>);
